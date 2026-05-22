# Cowork MCP Servers

Two small, self-contained [Model Context Protocol](https://modelcontextprotocol.io)
servers that expose marketplace seller data to MCP clients such as Claude Desktop:

- **`walmart/`** — Walmart Marketplace API (catalog items, inventory, orders)
- **`amazon/`** — Amazon Selling Partner API / SP-API (orders, FBA inventory, listings, reports)

Each server is a single Python file with dependencies declared inline via
[PEP 723](https://peps.python.org/pep-0723/), so [`uv`](https://docs.astral.sh/uv/)
runs it with no separate install step. **No credentials are stored in this
repository** — every server reads its secrets from environment variables at
runtime.

## Requirements

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Developer credentials for the marketplace(s) you want to use

## Walmart server

| Variable | Required | Description |
| --- | --- | --- |
| `WALMART_CLIENT_ID` | yes | Walmart developer client ID |
| `WALMART_CLIENT_SECRET` | yes | Walmart developer client secret |
| `WALMART_BASE_URL` | no | Defaults to `https://marketplace.walmartapis.com` |
| `WALMART_SVC_NAME` | no | Defaults to `Walmart Marketplace` |

Run locally:

```bash
WALMART_CLIENT_ID=... WALMART_CLIENT_SECRET=... \
  uv run walmart/walmart_1p_mcp.py
```

Tools: `walmart_list_items`, `walmart_get_item`, `walmart_get_inventory`,
`walmart_get_orders`, `walmart_diagnostics`.

See [`walmart/SETUP-WALMART.md`](walmart/SETUP-WALMART.md) for a full setup walkthrough.

## Amazon server

| Variable | Required | Description |
| --- | --- | --- |
| `AMAZON_CLIENT_ID` | yes | LWA client ID (`amzn1.application-oa2-client.*`) |
| `AMAZON_CLIENT_SECRET` | yes | LWA client secret |
| `AMAZON_REFRESH_TOKEN` | yes | Self-authorized refresh token (`Atzr|...`) |
| `AMAZON_REGION` | no | `na` \| `eu` \| `fe`. Default: `na` |
| `AMAZON_MARKETPLACE_ID` | no | Default marketplace. Default: `ATVPDKIKX0DER` (US) |
| `AMAZON_SELLER_ID` | no | Merchant Token. Auto-discovered on first call if unset |
| `AMAZON_LWA_ENDPOINT` | no | Defaults to `https://api.amazon.com/auth/o2/token` |

Run locally:

```bash
AMAZON_CLIENT_ID=... AMAZON_CLIENT_SECRET=... AMAZON_REFRESH_TOKEN=... \
  uv run amazon/amazon_sp_mcp.py
```

Tools: `amazon_diagnostics`, `amazon_get_marketplace_participations`,
`amazon_get_orders`, `amazon_get_order`, `amazon_get_order_items`,
`amazon_get_fba_inventory`, `amazon_search_listings`, `amazon_get_listing`,
`amazon_request_report`, `amazon_get_report`, `amazon_get_report_document`.

## Registering with an MCP client

Add an entry per server to your client's MCP config, supplying credentials via
the `env` block. Example for Claude Desktop
(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "walmart-1p": {
      "command": "/absolute/path/to/uv",
      "args": ["run", "/absolute/path/to/walmart/walmart_1p_mcp.py"],
      "env": {
        "WALMART_CLIENT_ID": "...",
        "WALMART_CLIENT_SECRET": "..."
      }
    }
  }
}
```

> The config file holding your real credentials should stay on your machine —
> keep it out of version control. This repo's `.gitignore` already excludes
> `claude_desktop_config.json` and common secret/env file patterns.

## License

MIT
