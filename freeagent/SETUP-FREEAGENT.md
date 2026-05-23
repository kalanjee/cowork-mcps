# FreeAgent MCP — Setup Guide

This adds a FreeAgent connector to your MCP client (Claude Desktop, Cowork, etc.) so it can read and modify the books in your FreeAgent account. The server runs locally on your computer, so your `client_secret` and `refresh_token` never leave it.

## What you need

1. `freeagent_mcp.py` and `freeagent_auth.py` (the two files in this folder).
2. A FreeAgent **Developer Dashboard** account (free) and a registered app.
3. `uv` installed.
4. An MCP client (e.g. Claude Desktop).

## Step 1 — Install uv

`uv` is a single-binary Python runner that handles dependencies automatically. If you don't have it, open Terminal and run:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen Terminal so `uv` is on your `PATH`. Verify with `uv --version`.

## Step 2 — Register an app in the FreeAgent Developer Dashboard

1. Sign in at <https://dev.freeagent.com>.
2. Create a new app (any name and description). You'll get an **OAuth identifier (Client ID)** and an **OAuth secret (Client Secret)**.
3. In the app's **Redirect URI(s)** field, add this exact value:
   ```
   http://localhost:8000/callback
   ```
   Save the app.

> Sandbox vs production: the same Developer Dashboard hosts apps for both, but each registered app is for one environment. To test against sandbox you also need a free sandbox FreeAgent account from <https://signup.sandbox.freeagent.com/signup>. Production app credentials will not authorize against sandbox and vice versa.

## Step 3 — Run the one-time authorization

In Terminal, run the auth helper. It will open your browser, you approve the app, and it prints a long-lived refresh token.

```
uv run freeagent/freeagent_auth.py
```

You can pre-fill the environment to skip prompts:

```
FREEAGENT_BASE_URL="https://api.freeagent.com/v2" \
FREEAGENT_CLIENT_ID="<your client id>" \
  uv run freeagent/freeagent_auth.py
```

The script will prompt for the **OAuth secret** (hidden input). Then your browser opens to FreeAgent — click **Approve**. After the redirect, the Terminal prints:

```
FREEAGENT_BASE_URL      = https://api.freeagent.com/v2
FREEAGENT_REFRESH_TOKEN = ...
```

The refresh token is effectively permanent (FreeAgent issues them with a ~20-year expiry).

## Step 4 — Add the MCP server to your client

For **Claude Desktop**, edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and add an entry under `mcpServers`:

```json
"freeagent": {
  "command": "/path/to/uv",
  "args": [
    "run",
    "/path/to/freeagent/freeagent_mcp.py"
  ],
  "env": {
    "FREEAGENT_BASE_URL": "https://api.freeagent.com/v2",
    "FREEAGENT_CLIENT_ID": "...",
    "FREEAGENT_CLIENT_SECRET": "...",
    "FREEAGENT_REFRESH_TOKEN": "..."
  }
}
```

Replace `/path/to/uv` with the output of `which uv`, and `/path/to/freeagent/freeagent_mcp.py` with the absolute path to the script on your machine.

Fully quit and reopen Claude Desktop. Ask it to run `freeagent_diagnostics` to confirm.

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `FREEAGENT_CLIENT_ID` | yes | OAuth identifier from the Developer Dashboard |
| `FREEAGENT_CLIENT_SECRET` | yes | OAuth secret |
| `FREEAGENT_REFRESH_TOKEN` | yes | Output of `freeagent_auth.py` |
| `FREEAGENT_BASE_URL` | no | Defaults to `https://api.freeagent.com/v2`. Use `https://api.sandbox.freeagent.com/v2` for sandbox |

## Security notes

- No credentials are stored in this repository or in the scripts themselves — everything reads from environment variables.
- The auth helper binds only to `localhost`. The redirect URI uses `http://` because RFC 8252 specifies loopback redirect URIs for native apps.
- Access tokens are cached in process memory only (never written to disk) and last about an hour.
- The refresh token grants full access to anything the authorizing user can do in the FreeAgent account. Treat it like a password.
- This server exposes write tools that can create, modify, and delete records in your books. Review write payloads before approving them.
