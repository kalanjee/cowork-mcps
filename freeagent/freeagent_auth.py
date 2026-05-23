# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""One-time FreeAgent OAuth authorization for the MCP server.

Run this once from a terminal. It opens your browser, you approve the app,
and it prints the long-lived refresh token to paste into the MCP client's
env block alongside the client id and secret.

  uv run freeagent/freeagent_auth.py

The app's Developer Dashboard must list this exact redirect URI:
  http://localhost:8000/callback
"""
import getpass
import http.server
import os
import sys
import urllib.parse
import webbrowser

import httpx

REDIRECT_URI = "http://localhost:8000/callback"
PORT = 8000
SANDBOX_BASE = "https://api.sandbox.freeagent.com/v2"
PRODUCTION_BASE = "https://api.freeagent.com/v2"
USER_AGENT = "cowork-freeagent-auth/0.1"

_result: dict[str, str | None] = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        _result["code"] = qs.get("code", [None])[0]
        _result["error"] = qs.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<h2>FreeAgent authorization received.</h2>"
            b"<p>You can close this tab and return to the terminal.</p>"
        )

    def log_message(self, *args):  # silence default request logging
        pass


def main() -> None:
    base = os.environ.get("FREEAGENT_BASE_URL")
    if not base:
        env = input("Environment [sandbox/production] (default sandbox): ").strip().lower()
        base = PRODUCTION_BASE if env.startswith("prod") else SANDBOX_BASE
    base = base.rstrip("/")

    client_id = os.environ.get("FREEAGENT_CLIENT_ID") or input("OAuth identifier (Client ID): ").strip()
    client_secret = os.environ.get("FREEAGENT_CLIENT_SECRET") or getpass.getpass(
        "OAuth secret (Client Secret, hidden): "
    ).strip()

    approve_url = f"{base}/approve_app?" + urllib.parse.urlencode(
        {"client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT_URI}
    )

    server = http.server.HTTPServer(("localhost", PORT), _CallbackHandler)
    print(f"\nOpening your browser to authorize the app.")
    print(f"If it does not open, paste this URL manually:\n{approve_url}\n")
    webbrowser.open(approve_url)
    print(f"Waiting for the redirect on {REDIRECT_URI} ...")

    while "code" not in _result and "error" not in _result:
        server.handle_request()
    server.server_close()

    if _result.get("error"):
        print(f"\nAuthorization failed: {_result['error']}")
        sys.exit(1)

    resp = httpx.post(
        f"{base}/token_endpoint",
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": _result["code"],
            "redirect_uri": REDIRECT_URI,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"\nToken exchange failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    tokens = resp.json()

    print("\n=== SUCCESS — add these to the MCP client's env block ===\n")
    print(f"FREEAGENT_BASE_URL      = {base}")
    print(f"FREEAGENT_REFRESH_TOKEN = {tokens['refresh_token']}")
    print("\n(Also set FREEAGENT_CLIENT_ID and FREEAGENT_CLIENT_SECRET in the same env block.)")


if __name__ == "__main__":
    main()
