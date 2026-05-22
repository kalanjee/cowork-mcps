# Walmart 1P MCP — Setup Guide

This adds a Walmart connector to Cowork so the morning check-in artifact can pull live data about your Walmart 1P items and sales. The server runs locally on your Mac, so your `client_secret` never leaves your computer.

## What you need

1. `walmart_1p_mcp.py` (the file sent alongside this guide).
2. Your Walmart developer **client ID** and **client secret**. You'll set these as environment variables — never paste them into a chat.
3. Cowork (Claude Desktop) installed.

## Step 1 — Install uv

`uv` is a single-binary Python runner that handles dependencies automatically. If you don't have it yet, open Terminal and run:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen Terminal so `uv` is on your `PATH`. Verify with:

```
uv --version
```

## Step 2 — Save the MCP server file

Put `walmart_1p_mcp.py` somewhere stable. A reasonable choice:

```
mkdir -p ~/cowork-mcps/walmart
mv ~/Downloads/walmart_1p_mcp.py ~/cowork-mcps/walmart/walmart_1p_mcp.py
```

The full absolute path you'll need below is:

```
/Users/<your-username>/cowork-mcps/walmart/walmart_1p_mcp.py
```

## Step 3 — Test it locally first

Run a quick sanity check before wiring it into Cowork. In Terminal:

```
WALMART_CLIENT_ID="your_client_id" \
WALMART_CLIENT_SECRET="your_client_secret" \
uv run ~/cowork-mcps/walmart/walmart_1p_mcp.py
```

The first run takes a few seconds while uv resolves dependencies. Once you see no errors and the process is waiting on stdin, the server is healthy. Press Ctrl-C to stop it.

If you get an error about token request failure, see the **Troubleshooting** section at the bottom — you may need to adjust the base URL or service name for the 1P Supplier API.

## Step 4 — Register the MCP in Cowork (Claude Desktop)

Cowork reads MCP servers from `~/Library/Application Support/Claude/claude_desktop_config.json`. Open it in any text editor:

```
open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

If the file already has `mcpServers`, add a new entry inside it. If not, the full file should look like this (replace the placeholder values):

```json
{
  "mcpServers": {
    "walmart-1p": {
      "command": "uv",
      "args": [
        "run",
        "/Users/<your-username>/cowork-mcps/walmart/walmart_1p_mcp.py"
      ],
      "env": {
        "WALMART_CLIENT_ID": "your_client_id_here",
        "WALMART_CLIENT_SECRET": "your_client_secret_here"
      }
    }
  }
}
```

A few notes:

- The path in `args` must be absolute. Replace `<your-username>` with the result of `whoami` in Terminal.
- If `uv` isn't found, replace `"command": "uv"` with the output of `which uv` (the full path).
- The secret stays in this file, on your disk, never in a chat. If you want extra isolation, you can use `1Password CLI` or a similar tool to inject env vars — happy to walk through that if you want.

Save the file.

## Step 5 — Restart Cowork

Fully quit Cowork (cmd-Q, not just close the window) and reopen it. When it boots, it will spawn the Walmart MCP as a child process and probe its tools.

## Step 6 — Verify

In any Cowork chat, type:

```
List my Walmart MCP tools and run walmart_diagnostics
```

You should see five tools (`walmart_list_items`, `walmart_get_item`, `walmart_get_inventory`, `walmart_get_orders`, `walmart_diagnostics`) and a diagnostics result like:

```
{
  "base_url": "https://marketplace.walmartapis.com",
  "svc_name": "Walmart Marketplace",
  "client_id_set": true,
  "client_secret_set": true,
  "token_cached": false,
  "token_expires_in_seconds": 0
}
```

If both `client_id_set` and `client_secret_set` are `true`, the server is wired up. The token will appear after the first real call (e.g. `walmart_list_items`).

## Step 7 — Tell me you're done

Come back to the chat where we've been building the morning check-in. Say "Walmart MCP is connected" and share the connector's UUID. Cowork generates a UUID for each connected MCP server; you can find it by asking in chat:

```
What's the UUID for my walmart-1p MCP server?
```

Once you give me that UUID, I'll wire the artifact's Walmart panel: status of each item (publish state) + last-7-days sales pulled from `walmart_get_orders`.

---

## Troubleshooting

**`Walmart token request failed (401)`** — Credentials are wrong, expired, or your account isn't authorized for the API you're hitting. Double-check the client ID/secret in the Walmart developer portal.

**`Walmart token request failed (404)` or 200 OK but `walmart_list_items` returns 404** — You're likely on the 1P Supplier API rather than the Marketplace API. The base URL and service name are different. Try editing the `env` in your Cowork config to add:

```json
"WALMART_BASE_URL": "https://api.walmart.com",
"WALMART_SVC_NAME": "Walmart Supplier"
```

(Exact values depend on which Walmart developer portal you registered on — let me know which one and I'll confirm the right combination.)

**`uv: command not found` in Cowork logs** — Cowork's child processes don't see your shell `PATH` by default. Replace `"command": "uv"` with the full path you got from `which uv`.

**Tools don't appear after restart** — Open Console.app, search for "Claude", and look for errors. Most often it's a JSON syntax error in `claude_desktop_config.json` — paste it into <https://jsonlint.com/> to find the issue.
