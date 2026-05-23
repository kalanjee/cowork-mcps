# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2", "httpx>=0.27"]
# ///
"""FreeAgent MCP server.

Single-file MCP server exposing the FreeAgent accounting API to MCP clients
such as Claude Desktop. Covers read + write across the main resources
(company, bank, invoices, estimates, bills, expenses, contacts, projects,
tasks, timeslips, categories, users) plus generic GET/POST/PUT/DELETE
passthroughs for anything else FreeAgent exposes.

Reads credentials from environment:
  FREEAGENT_CLIENT_ID      OAuth identifier
  FREEAGENT_CLIENT_SECRET  OAuth secret
  FREEAGENT_REFRESH_TOKEN  Long-lived refresh token (from freeagent_auth.py)
  FREEAGENT_BASE_URL       API base. Production (default):
                           https://api.freeagent.com/v2
                           Sandbox: https://api.sandbox.freeagent.com/v2

Mints short-lived access tokens via the OAuth refresh-token grant and caches
them in-process for their lifetime (~1 hour).
"""
import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("FREEAGENT_BASE_URL", "https://api.freeagent.com/v2").rstrip("/")
CLIENT_ID = os.environ.get("FREEAGENT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("FREEAGENT_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("FREEAGENT_REFRESH_TOKEN", "")
TOKEN_ENDPOINT = f"{BASE_URL}/token_endpoint"
USER_AGENT = "cowork-freeagent-mcp/0.1"

mcp = FastMCP("freeagent")

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------

def _get_access_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"]:
        return _token_cache["access_token"]
    if not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN):
        raise RuntimeError(
            "Missing credentials. Set FREEAGENT_CLIENT_ID, FREEAGENT_CLIENT_SECRET "
            "and FREEAGENT_REFRESH_TOKEN in the MCP client's env block."
        )
    resp = httpx.post(
        TOKEN_ENDPOINT,
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    _token_cache["access_token"] = payload["access_token"]
    _token_cache["expires_at"] = now + payload.get("expires_in", 3600) - 120
    return _token_cache["access_token"]


def _resolve_url(path_or_url: str) -> str:
    return path_or_url if path_or_url.startswith("http") else f"{BASE_URL}/{path_or_url.lstrip('/')}"


def _request(method: str, path_or_url: str, *, params: dict | None = None, json_body: dict | None = None) -> Any:
    token = _get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    resp = httpx.request(
        method,
        _resolve_url(path_or_url),
        headers=headers,
        params={k: v for k, v in (params or {}).items() if v is not None} or None,
        json=json_body,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"FreeAgent API {resp.status_code} for {method} {resp.url}: {resp.text}")
    if resp.status_code == 204 or not resp.content:
        return {"status": "ok", "code": resp.status_code}
    ctype = resp.headers.get("content-type", "")
    if "application/json" in ctype:
        return resp.json()
    return {"status": "ok", "code": resp.status_code, "text": resp.text}


def _api_get(path: str, params: dict | None = None) -> Any:
    return _request("GET", path, params=params)


def _normalize(resource_plural: str, value: str) -> str:
    """Accept either a numeric ID or a full URL and return a full URL."""
    if value.startswith("http"):
        return value
    return f"{BASE_URL}/{resource_plural}/{value}"


# ---------------------------------------------------------------------------
# Diagnostics + Company
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_diagnostics() -> dict:
    """Check FreeAgent connectivity: verify env vars, refresh the access token,
    and fetch company info. Run this first to confirm the integration works."""
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "client_id_present": bool(CLIENT_ID),
        "client_secret_present": bool(CLIENT_SECRET),
        "refresh_token_present": bool(REFRESH_TOKEN),
    }
    try:
        _get_access_token()
        report["token_refresh"] = "ok"
    except Exception as exc:  # noqa: BLE001
        report["token_refresh"] = f"failed: {exc}"
        return report
    try:
        company = _api_get("company")
        report["company_name"] = company.get("company", {}).get("name", company)
        report["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        report["status"] = f"company fetch failed: {exc}"
    return report


@mcp.tool()
def freeagent_get_company() -> dict:
    """Fetch FreeAgent company details: name, type, currency, accounting dates, VAT status."""
    return _api_get("company")


@mcp.tool()
def freeagent_list_users() -> dict:
    """List users that have access to the FreeAgent account."""
    return _api_get("users")


# ---------------------------------------------------------------------------
# Bank accounts + transactions + explanations
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_bank_accounts() -> dict:
    """List all bank accounts with names, types, and current balances."""
    return _api_get("bank_accounts")


@mcp.tool()
def freeagent_get_bank_account(bank_account: str) -> dict:
    """Fetch a single bank account by ID or full URL."""
    return _api_get(_normalize("bank_accounts", bank_account))


@mcp.tool()
def freeagent_list_bank_transactions(
    bank_account: str,
    view: str = "all",
    from_date: str | None = None,
    to_date: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """List bank transactions for one account.

    bank_account: account ID or full URL from freeagent_list_bank_accounts.
    view: all | unexplained | explained | manual | imported | marked_for_review.
    from_date / to_date: YYYY-MM-DD.
    """
    return _api_get(
        "bank_transactions",
        {
            "bank_account": _normalize("bank_accounts", bank_account),
            "view": view,
            "from_date": from_date,
            "to_date": to_date,
            "page": page,
            "per_page": per_page,
        },
    )


@mcp.tool()
def freeagent_list_bank_transaction_explanations(
    bank_account: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    updated_since: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """List bank transaction explanations (the categorized entries against bank transactions)."""
    return _api_get(
        "bank_transaction_explanations",
        {
            "bank_account": _normalize("bank_accounts", bank_account) if bank_account else None,
            "from_date": from_date,
            "to_date": to_date,
            "updated_since": updated_since,
            "page": page,
            "per_page": per_page,
        },
    )


@mcp.tool()
def freeagent_explain_bank_transaction(
    bank_transaction: str,
    dated_on: str,
    gross_value: str,
    category: str | None = None,
    description: str | None = None,
    sales_tax_rate: str | None = None,
    sales_tax_value: str | None = None,
    extra_fields: dict | None = None,
) -> dict:
    """Categorize a bank transaction by creating a bank_transaction_explanation.

    bank_transaction: the transaction ID or full URL.
    dated_on: YYYY-MM-DD.
    gross_value: signed string, e.g. "-49.99" for an outflow, "120.00" for an inflow.
    category: category URL or ID from freeagent_list_categories (omit to leave uncategorized).
    description: free-text note.
    sales_tax_rate / sales_tax_value: VAT, when applicable.
    extra_fields: dict merged into the payload for advanced cases (e.g. project, contact,
                  manual_sales_tax_amount, recurring, attachment).
    """
    payload: dict[str, Any] = {
        "bank_transaction": _normalize("bank_transactions", bank_transaction),
        "dated_on": dated_on,
        "gross_value": gross_value,
    }
    if category is not None:
        payload["category"] = _normalize("categories", category)
    if description is not None:
        payload["description"] = description
    if sales_tax_rate is not None:
        payload["sales_tax_rate"] = sales_tax_rate
    if sales_tax_value is not None:
        payload["sales_tax_value"] = sales_tax_value
    if extra_fields:
        payload.update(extra_fields)
    return _request("POST", "bank_transaction_explanations", json_body={"bank_transaction_explanation": payload})


@mcp.tool()
def freeagent_update_bank_transaction_explanation(explanation: str, fields: dict) -> dict:
    """Update fields on a bank transaction explanation.

    explanation: ID or full URL of the explanation.
    fields: dict of attributes to change (e.g. {"category": "<url>", "description": "..."}).
    """
    return _request(
        "PUT",
        _normalize("bank_transaction_explanations", explanation),
        json_body={"bank_transaction_explanation": fields},
    )


@mcp.tool()
def freeagent_delete_bank_transaction_explanation(explanation: str) -> dict:
    """Delete a bank transaction explanation (un-categorize). Only allowed when
    the explanation's is_deletable flag is true."""
    return _request("DELETE", _normalize("bank_transaction_explanations", explanation))


# ---------------------------------------------------------------------------
# Categories (chart of accounts)
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_categories() -> dict:
    """List all accounting categories (income, cost of sales, admin expenses, general).

    Use the returned `url` values when explaining bank transactions, creating bills, etc.
    """
    return _api_get("categories")


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_contacts(view: str = "all", page: int = 1, per_page: int = 100) -> dict:
    """List contacts. view: all | active | clients | suppliers."""
    return _api_get("contacts", {"view": view, "page": page, "per_page": per_page})


@mcp.tool()
def freeagent_get_contact(contact: str) -> dict:
    """Fetch a single contact by ID or full URL."""
    return _api_get(_normalize("contacts", contact))


@mcp.tool()
def freeagent_create_contact(fields: dict) -> dict:
    """Create a contact.

    fields: contact attributes. Must include EITHER organisation_name OR
    (first_name AND last_name). Common optional: email, billing_email, phone_number,
    address1, town, region, postcode, country, contact_name_on_invoices, default_payment_terms_in_days.
    """
    return _request("POST", "contacts", json_body={"contact": fields})


@mcp.tool()
def freeagent_update_contact(contact: str, fields: dict) -> dict:
    """Update a contact. contact: ID or full URL. fields: only the attributes to change."""
    return _request("PUT", _normalize("contacts", contact), json_body={"contact": fields})


@mcp.tool()
def freeagent_delete_contact(contact: str) -> dict:
    """Delete a contact. Will fail if the contact has any associated records."""
    return _request("DELETE", _normalize("contacts", contact))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_invoices(
    view: str = "all",
    sort: str = "-created_at",
    updated_since: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """List invoices.

    view: all | open | overdue | open_or_overdue | draft | paid |
          recent_open_or_overdue | last_N_months.
    """
    return _api_get(
        "invoices",
        {"view": view, "sort": sort, "updated_since": updated_since, "page": page, "per_page": per_page},
    )


@mcp.tool()
def freeagent_get_invoice(invoice: str) -> dict:
    """Fetch a single invoice (with its line items) by ID or full URL."""
    return _api_get(_normalize("invoices", invoice))


@mcp.tool()
def freeagent_create_invoice(fields: dict) -> dict:
    """Create an invoice.

    fields: invoice attributes. Required: contact (URL), dated_on (YYYY-MM-DD),
    payment_terms_in_days (int), currency (e.g. "GBP"), invoice_items (list of
    {description, quantity, price, sales_tax_rate, category, ...}).
    Common optional: reference, comments, project, payment_methods.
    """
    return _request("POST", "invoices", json_body={"invoice": fields})


@mcp.tool()
def freeagent_update_invoice(invoice: str, fields: dict) -> dict:
    """Update an invoice. fields: only the attributes to change."""
    return _request("PUT", _normalize("invoices", invoice), json_body={"invoice": fields})


@mcp.tool()
def freeagent_delete_invoice(invoice: str) -> dict:
    """Delete an invoice. Usually only allowed for drafts."""
    return _request("DELETE", _normalize("invoices", invoice))


@mcp.tool()
def freeagent_mark_invoice(invoice: str, state: str) -> dict:
    """Transition an invoice's state.

    state: sent | draft | cancelled | scheduled. Calls PUT /invoices/:id/transitions/mark_as_<state>.
    """
    allowed = {"sent", "draft", "cancelled", "scheduled"}
    if state not in allowed:
        raise ValueError(f"state must be one of {sorted(allowed)}")
    return _request("PUT", f"{_normalize('invoices', invoice)}/transitions/mark_as_{state}")


@mcp.tool()
def freeagent_send_invoice_email(invoice: str, email_fields: dict | None = None) -> dict:
    """Email an invoice to its contact.

    email_fields (optional): dict with optional keys like to_address, cc_address,
    from_address, subject, body, send_self_copy. If omitted, FreeAgent uses the
    saved defaults for the contact.
    """
    body = {"invoice_email": email_fields or {}}
    return _request("POST", f"{_normalize('invoices', invoice)}/send_email", json_body=body)


# ---------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_estimates(view: str = "all", page: int = 1, per_page: int = 100) -> dict:
    """List estimates / quotes. view: all | draft | sent | approved | rejected | invoiced."""
    return _api_get("estimates", {"view": view, "page": page, "per_page": per_page})


@mcp.tool()
def freeagent_get_estimate(estimate: str) -> dict:
    """Fetch a single estimate."""
    return _api_get(_normalize("estimates", estimate))


@mcp.tool()
def freeagent_create_estimate(fields: dict) -> dict:
    """Create an estimate. Similar shape to invoices (contact, dated_on, currency, estimate_items)."""
    return _request("POST", "estimates", json_body={"estimate": fields})


@mcp.tool()
def freeagent_update_estimate(estimate: str, fields: dict) -> dict:
    """Update an estimate."""
    return _request("PUT", _normalize("estimates", estimate), json_body={"estimate": fields})


@mcp.tool()
def freeagent_delete_estimate(estimate: str) -> dict:
    """Delete an estimate."""
    return _request("DELETE", _normalize("estimates", estimate))


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_bills(view: str = "all", page: int = 1, per_page: int = 100) -> dict:
    """List bills (money you owe). view: all | open | overdue | paid | recurring."""
    return _api_get("bills", {"view": view, "page": page, "per_page": per_page})


@mcp.tool()
def freeagent_get_bill(bill: str) -> dict:
    """Fetch a single bill."""
    return _api_get(_normalize("bills", bill))


@mcp.tool()
def freeagent_create_bill(fields: dict) -> dict:
    """Create a bill.

    fields: bill attributes. Required: contact (URL), dated_on (YYYY-MM-DD),
    due_on (YYYY-MM-DD), reference, total_value, category (URL).
    Optional: sales_tax_rate, sales_tax_value, ec_status, description, project.
    """
    return _request("POST", "bills", json_body={"bill": fields})


@mcp.tool()
def freeagent_update_bill(bill: str, fields: dict) -> dict:
    """Update a bill."""
    return _request("PUT", _normalize("bills", bill), json_body={"bill": fields})


@mcp.tool()
def freeagent_delete_bill(bill: str) -> dict:
    """Delete a bill."""
    return _request("DELETE", _normalize("bills", bill))


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_expenses(
    view: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    updated_since: str | None = None,
    user: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """List expenses. Optional filters: view, from_date/to_date (YYYY-MM-DD),
    updated_since (ISO 8601), user (ID or URL)."""
    return _api_get(
        "expenses",
        {
            "view": view,
            "from_date": from_date,
            "to_date": to_date,
            "updated_since": updated_since,
            "user": _normalize("users", user) if user else None,
            "page": page,
            "per_page": per_page,
        },
    )


@mcp.tool()
def freeagent_get_expense(expense: str) -> dict:
    """Fetch a single expense."""
    return _api_get(_normalize("expenses", expense))


@mcp.tool()
def freeagent_create_expense(fields: dict) -> dict:
    """Create an expense.

    fields: expense attributes. Required: user (URL), category (URL),
    dated_on (YYYY-MM-DD), gross_value, description.
    Optional: sales_tax_rate, manual_sales_tax_amount, currency, native_gross_value,
    project, rebill_type, mileage, attachment.
    """
    return _request("POST", "expenses", json_body={"expense": fields})


@mcp.tool()
def freeagent_update_expense(expense: str, fields: dict) -> dict:
    """Update an expense."""
    return _request("PUT", _normalize("expenses", expense), json_body={"expense": fields})


@mcp.tool()
def freeagent_delete_expense(expense: str) -> dict:
    """Delete an expense."""
    return _request("DELETE", _normalize("expenses", expense))


# ---------------------------------------------------------------------------
# Projects, tasks, timeslips
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_projects(view: str = "active", page: int = 1, per_page: int = 100) -> dict:
    """List projects. view: active | completed | cancelled | hidden | all."""
    return _api_get("projects", {"view": view, "page": page, "per_page": per_page})


@mcp.tool()
def freeagent_get_project(project: str) -> dict:
    """Fetch a single project."""
    return _api_get(_normalize("projects", project))


@mcp.tool()
def freeagent_create_project(fields: dict) -> dict:
    """Create a project. Required fields typically: contact (URL), name, currency, budget_units."""
    return _request("POST", "projects", json_body={"project": fields})


@mcp.tool()
def freeagent_update_project(project: str, fields: dict) -> dict:
    """Update a project."""
    return _request("PUT", _normalize("projects", project), json_body={"project": fields})


@mcp.tool()
def freeagent_delete_project(project: str) -> dict:
    """Delete a project."""
    return _request("DELETE", _normalize("projects", project))


@mcp.tool()
def freeagent_list_tasks(project: str | None = None, page: int = 1, per_page: int = 100) -> dict:
    """List project tasks. Optionally scope to one project (ID or URL)."""
    return _api_get(
        "tasks",
        {"project": _normalize("projects", project) if project else None, "page": page, "per_page": per_page},
    )


@mcp.tool()
def freeagent_list_timeslips(
    view: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    user: str | None = None,
    project: str | None = None,
    updated_since: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict:
    """List timeslips. Filter by view (all | unbilled | running), date range, user, project."""
    return _api_get(
        "timeslips",
        {
            "view": view,
            "from_date": from_date,
            "to_date": to_date,
            "user": _normalize("users", user) if user else None,
            "project": _normalize("projects", project) if project else None,
            "updated_since": updated_since,
            "page": page,
            "per_page": per_page,
        },
    )


# ---------------------------------------------------------------------------
# Recurring invoices
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_list_recurring_invoices(view: str = "all", page: int = 1, per_page: int = 100) -> dict:
    """List recurring invoice profiles."""
    return _api_get("recurring_invoices", {"view": view, "page": page, "per_page": per_page})


# ---------------------------------------------------------------------------
# Generic passthroughs (long tail: reports, journal entries, attachments, etc.)
# ---------------------------------------------------------------------------

@mcp.tool()
def freeagent_get(path: str, params: dict | None = None) -> Any:
    """Generic authenticated GET against any FreeAgent endpoint.

    Path is relative to the API base (leading slash optional). Use this for
    anything not covered by a dedicated tool — e.g. 'profit_and_loss', 'trial_balance',
    'corporation_tax_returns', 'attachments/:id'.
    """
    return _api_get(path, params)


@mcp.tool()
def freeagent_post(path: str, body: dict) -> Any:
    """Generic authenticated POST. Pass the full payload including the resource
    wrapper key (e.g. {"bill": {...}})."""
    return _request("POST", path, json_body=body)


@mcp.tool()
def freeagent_put(path: str, body: dict) -> Any:
    """Generic authenticated PUT. Pass the full payload including the resource wrapper key."""
    return _request("PUT", path, json_body=body)


@mcp.tool()
def freeagent_delete(path: str) -> Any:
    """Generic authenticated DELETE. Pass a path or full URL."""
    return _request("DELETE", path)


if __name__ == "__main__":
    mcp.run()
