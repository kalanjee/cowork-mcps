# Cowork MCP Servers

Three small, self-contained [Model Context Protocol](https://modelcontextprotocol.io)
servers that expose seller and accounting data to MCP clients such as Claude Desktop:

- **`walmart/`** — Walmart Marketplace API (catalog items, inventory, orders)
- **`amazon/`** — Amazon Selling Partner API / SP-API (orders, FBA inventory, listings, reports)
- **`freeagent/`** — FreeAgent accounting API (bank, invoices, bills, expenses, contacts, projects; full read + write)

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

## FreeAgent server

| Variable | Required | Description |
| --- | --- | --- |
| `FREEAGENT_CLIENT_ID` | yes | OAuth identifier from the FreeAgent Developer Dashboard |
| `FREEAGENT_CLIENT_SECRET` | yes | OAuth secret |
| `FREEAGENT_REFRESH_TOKEN` | yes | Long-lived refresh token (run `freeagent/freeagent_auth.py` once to obtain) |
| `FREEAGENT_BASE_URL` | no | Defaults to `https://api.freeagent.com/v2`. Use `https://api.sandbox.freeagent.com/v2` for sandbox |

One-time authorization (opens your browser, prints the refresh token):

```bash
uv run freeagent/freeagent_auth.py
```

Then run the server:

```bash
FREEAGENT_CLIENT_ID=... FREEAGENT_CLIENT_SECRET=... FREEAGENT_REFRESH_TOKEN=... \
  uv run freeagent/freeagent_mcp.py
```

Tools span the main FreeAgent resources with full read + write coverage:
`freeagent_diagnostics`, `freeagent_get_company`, `freeagent_list_users`,
`freeagent_list_bank_accounts`, `freeagent_get_bank_account`,
`freeagent_list_bank_transactions`, `freeagent_list_bank_transaction_explanations`,
`freeagent_explain_bank_transaction`, `freeagent_update_bank_transaction_explanation`,
`freeagent_delete_bank_transaction_explanation`, `freeagent_list_categories`,
`freeagent_list_contacts`, `freeagent_get_contact`, `freeagent_create_contact`,
`freeagent_update_contact`, `freeagent_delete_contact`, `freeagent_list_invoices`,
`freeagent_get_invoice`, `freeagent_create_invoice`, `freeagent_update_invoice`,
`freeagent_delete_invoice`, `freeagent_mark_invoice`, `freeagent_send_invoice_email`,
`freeagent_list_estimates`, `freeagent_get_estimate`, `freeagent_create_estimate`,
`freeagent_update_estimate`, `freeagent_delete_estimate`, `freeagent_list_bills`,
`freeagent_get_bill`, `freeagent_create_bill`, `freeagent_update_bill`,
`freeagent_delete_bill`, `freeagent_list_expenses`, `freeagent_get_expense`,
`freeagent_create_expense`, `freeagent_update_expense`, `freeagent_delete_expense`,
`freeagent_list_projects`, `freeagent_get_project`, `freeagent_create_project`,
`freeagent_update_project`, `freeagent_delete_project`, `freeagent_list_tasks`,
`freeagent_list_timeslips`, `freeagent_list_recurring_invoices`, and generic
`freeagent_get` / `freeagent_post` / `freeagent_put` / `freeagent_delete`
passthroughs for the long tail (reports, journal entries, attachments, etc.).

See [`freeagent/SETUP-FREEAGENT.md`](freeagent/SETUP-FREEAGENT.md) for a full setup walkthrough.

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
