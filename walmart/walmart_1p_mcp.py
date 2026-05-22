#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "httpx>=0.27",
# ]
# ///
"""
Walmart 1P MCP Server
=====================

A minimal Model Context Protocol server that exposes Walmart's Marketplace /
Supplier API to Cowork. Handles OAuth client_credentials token refresh and
provides four read-only tools: list items, get item, get inventory, get orders.

Run locally with uv:
    uv run walmart_1p_mcp.py

Or, if installed permanently, add to your Cowork (Claude Desktop) config so
the server starts automatically. See SETUP-WALMART.md for full instructions.

ENVIRONMENT VARIABLES
---------------------
    WALMART_CLIENT_ID         (required)  Your Walmart developer client ID.
    WALMART_CLIENT_SECRET     (required)  Your Walmart developer client secret.
    WALMART_BASE_URL          (optional)  Defaults to https://marketplace.walmartapis.com
                                          For 1P Supplier API, you may need a different
                                          base URL such as https://api.walmart.com
    WALMART_SVC_NAME          (optional)  Defaults to "Walmart Marketplace"
                                          Some Walmart APIs expect "Walmart Supplier"
                                          or another value in the WM_SVC.NAME header.
"""
import asyncio
import base64
import logging
import os
import time
import uuid
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CLIENT_ID = os.environ.get("WALMART_CLIENT_ID")
CLIENT_SECRET = os.environ.get("WALMART_CLIENT_SECRET")
BASE_URL = os.environ.get("WALMART_BASE_URL", "https://marketplace.walmartapis.com").rstrip("/")
SVC_NAME = os.environ.get("WALMART_SVC_NAME", "Walmart Marketplace")

logger = logging.getLogger("walmart-1p-mcp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------
_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


async def _get_access_token() -> str:
    """OAuth 2.0 client_credentials flow with a small in-memory cache."""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "WALMART_CLIENT_ID and WALMART_CLIENT_SECRET must be set in the environment."
        )

    async with _token_lock:
        if _token_cache["access_token"] and _token_cache["expires_at"] > time.time() + 30:
            return _token_cache["access_token"]

        basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        headers = {
            "Authorization": f"Basic {basic}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
            "WM_SVC.NAME": SVC_NAME,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{BASE_URL}/v3/token",
                headers=headers,
                data={"grant_type": "client_credentials"},
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"Walmart token request failed ({r.status_code}): {r.text[:400]}"
                )
            j = r.json()
            _token_cache["access_token"] = j["access_token"]
            ttl = int(j.get("expires_in", 600))
            _token_cache["expires_at"] = time.time() + ttl
            logger.info("Refreshed Walmart access token (ttl=%ss)", ttl)
            return _token_cache["access_token"]


async def _api_get(path: str, params: dict | None = None) -> dict:
    token = await _get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "WM_SEC.ACCESS_TOKEN": token,
        "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
        "WM_SVC.NAME": SVC_NAME,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{BASE_URL}{path}", params=params, headers=headers)
        if r.status_code >= 400:
            return {
                "error": True,
                "status": r.status_code,
                "message": r.text[:600],
                "url": f"{BASE_URL}{path}",
                "hint": (
                    "If you see 401/403, your credentials or scope are wrong. If you see 404, "
                    "the path may differ between Marketplace and Supplier APIs — try setting "
                    "WALMART_BASE_URL and WALMART_SVC_NAME to match your account type."
                ),
            }
        # Some Walmart endpoints return XML by default; ask for JSON via headers above.
        try:
            return r.json()
        except Exception:
            return {"raw": r.text[:2000], "contentType": r.headers.get("content-type", "?")}


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
mcp = FastMCP("walmart-1p")


@mcp.tool()
async def walmart_list_items(limit: int = 50, next_cursor: str | None = None) -> dict:
    """List items in your Walmart catalog with publish status.

    Args:
        limit: How many items to return per page (1-50).
        next_cursor: Pass the `nextCursor` value from a previous response to paginate.

    Returns the raw Walmart Items API response (typically includes `ItemResponse` array
    with `mart`, `sku`, `wpid`, `productName`, `price`, `publishedStatus`, etc).
    """
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 50))}
    if next_cursor:
        params["nextCursor"] = next_cursor
    return await _api_get("/v3/items", params)


@mcp.tool()
async def walmart_get_item(sku: str) -> dict:
    """Fetch a single Walmart item by its seller SKU.

    Args:
        sku: The seller SKU as registered on Walmart.
    """
    if not sku:
        return {"error": True, "message": "sku is required"}
    return await _api_get(f"/v3/items/{sku}")


@mcp.tool()
async def walmart_get_inventory(sku: str) -> dict:
    """Fetch on-hand inventory for a single SKU."""
    if not sku:
        return {"error": True, "message": "sku is required"}
    return await _api_get("/v3/inventory", {"sku": sku})


@mcp.tool()
async def walmart_get_orders(
    created_start_date: str,
    created_end_date: str | None = None,
    status: str | None = None,
    limit: int = 50,
    next_cursor: str | None = None,
) -> dict:
    """Fetch Walmart orders since a given date — used for the sales-data feed.

    Args:
        created_start_date: ISO8601 timestamp, e.g. "2026-05-03T00:00:00Z".
        created_end_date: Optional ISO8601 end timestamp.
        status: Optional filter — Created, Acknowledged, Shipped, Delivered, Cancelled, Refund.
        limit: Page size (1-200).
        next_cursor: Pagination cursor from a previous response.

    Returns the raw orders payload with line items, totals, and statuses.
    """
    params: dict[str, Any] = {
        "createdStartDate": created_start_date,
        "limit": max(1, min(int(limit), 200)),
    }
    if created_end_date:
        params["createdEndDate"] = created_end_date
    if status:
        params["status"] = status
    if next_cursor:
        params["nextCursor"] = next_cursor
    return await _api_get("/v3/orders", params)


@mcp.tool()
async def walmart_diagnostics() -> dict:
    """Return basic config info (no secrets) so you can verify the server is wired up correctly."""
    return {
        "base_url": BASE_URL,
        "svc_name": SVC_NAME,
        "client_id_set": bool(CLIENT_ID),
        "client_secret_set": bool(CLIENT_SECRET),
        "token_cached": bool(_token_cache["access_token"]),
        "token_expires_in_seconds": max(0, int(_token_cache["expires_at"] - time.time())),
    }


if __name__ == "__main__":
    mcp.run()
