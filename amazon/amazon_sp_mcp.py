#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mcp>=1.2",
#   "httpx>=0.27",
# ]
# ///
"""
Amazon Selling Partner API (SP-API) MCP Server
==============================================

Minimal Model Context Protocol server that exposes Amazon Seller Central data
to Cowork. Handles LWA refresh-token flow and exposes read-only tools for
orders, FBA inventory, listings, and reports.

Run locally with uv:
    uv run amazon_sp_mcp.py

Or register it in Claude Desktop's config so it starts automatically.

ENVIRONMENT VARIABLES
---------------------
    AMAZON_CLIENT_ID          (required)  LWA client ID (amzn1.application-oa2-client.*)
    AMAZON_CLIENT_SECRET      (required)  LWA client secret (amzn1.oa2-cs.v1.*)
    AMAZON_REFRESH_TOKEN      (required)  Self-authorized refresh token (Atzr|...)
    AMAZON_REGION             (optional)  na | eu | fe. Default: na
    AMAZON_MARKETPLACE_ID     (optional)  Default marketplace. Default: ATVPDKIKX0DER (US)
    AMAZON_SELLER_ID          (optional)  Merchant Token. Auto-discovered on first call if unset.
    AMAZON_LWA_ENDPOINT       (optional)  Defaults to https://api.amazon.com/auth/o2/token
"""
import asyncio
import gzip
import io
import logging
import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CLIENT_ID = os.environ.get("AMAZON_CLIENT_ID")
CLIENT_SECRET = os.environ.get("AMAZON_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("AMAZON_REFRESH_TOKEN")
REGION = os.environ.get("AMAZON_REGION", "na").lower()
MARKETPLACE_ID = os.environ.get("AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER")
SELLER_ID_ENV = os.environ.get("AMAZON_SELLER_ID")
LWA_ENDPOINT = os.environ.get("AMAZON_LWA_ENDPOINT", "https://api.amazon.com/auth/o2/token")

_REGION_HOSTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}
BASE_URL = _REGION_HOSTS.get(REGION, _REGION_HOSTS["na"])

logger = logging.getLogger("amazon-sp-mcp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()
_seller_id_cache: dict[str, str | None] = {"value": SELLER_ID_ENV}
_seller_id_lock = asyncio.Lock()


async def _get_access_token() -> str:
    """LWA refresh_token grant with a small in-memory cache. Tokens last ~1h."""
    if not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN):
        raise RuntimeError(
            "AMAZON_CLIENT_ID, AMAZON_CLIENT_SECRET, and AMAZON_REFRESH_TOKEN must be set."
        )
    async with _token_lock:
        if _token_cache["access_token"] and _token_cache["expires_at"] > time.time() + 60:
            return _token_cache["access_token"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                LWA_ENDPOINT,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": REFRESH_TOKEN,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"LWA token request failed ({r.status_code}): {r.text[:500]}"
                )
            j = r.json()
            _token_cache["access_token"] = j["access_token"]
            ttl = int(j.get("expires_in", 3600))
            _token_cache["expires_at"] = time.time() + ttl
            logger.info("Refreshed LWA access token (ttl=%ss)", ttl)
            return _token_cache["access_token"]


def _err(resp: httpx.Response, path: str) -> dict:
    hint = None
    if resp.status_code in (401, 403):
        hint = (
            "401/403 usually means the app is missing a role for this endpoint, or the "
            "refresh token was issued before the role was added. Re-authorize the app in "
            "Seller Central if you've added roles recently."
        )
    elif resp.status_code == 429:
        hint = "Rate-limited. SP-API uses a leaky-bucket per endpoint; wait and retry."
    elif resp.status_code == 404:
        hint = "Check the path, marketplace ID, and seller ID."
    return {
        "error": True,
        "status": resp.status_code,
        "url": f"{BASE_URL}{path}",
        "message": resp.text[:800],
        "hint": hint,
    }


async def _request(method: str, path: str, *, params: dict | None = None, json_body: Any = None) -> dict:
    token = await _get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "x-amz-access-token": token,
        "Accept": "application/json",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.request(
            method, f"{BASE_URL}{path}", params=params, headers=headers, json=json_body
        )
        if r.status_code >= 400:
            return _err(r, path)
        if not r.content:
            return {"status": r.status_code}
        try:
            return r.json()
        except Exception:
            return {"raw": r.text[:2000], "contentType": r.headers.get("content-type", "?")}


async def _get(path: str, params: dict | None = None) -> dict:
    return await _request("GET", path, params=params)


async def _post(path: str, json_body: Any) -> dict:
    return await _request("POST", path, json_body=json_body)


async def _resolve_seller_id() -> str:
    """Fetch and cache the seller's Merchant Token via marketplace participations."""
    if _seller_id_cache["value"]:
        return _seller_id_cache["value"]
    async with _seller_id_lock:
        if _seller_id_cache["value"]:
            return _seller_id_cache["value"]
        data = await _get("/sellers/v1/marketplaceParticipations")
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Could not auto-discover Seller ID: {data}")
        # Response shape: {payload: [{marketplace: {...}, participation: {...}, sellerId?}, ...]}
        # Some accounts surface sellerId only at the participation level; try both.
        seller_id = None
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, list):
            for entry in payload:
                seller_id = (
                    entry.get("sellerId")
                    or entry.get("participation", {}).get("sellerId")
                )
                if seller_id:
                    break
        if not seller_id:
            raise RuntimeError(
                "Seller ID not found in marketplaceParticipations response — set "
                "AMAZON_SELLER_ID explicitly in your Cowork config."
            )
        _seller_id_cache["value"] = seller_id
        return seller_id


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
mcp = FastMCP("amazon-sp")


@mcp.tool()
async def amazon_diagnostics() -> dict:
    """Show config + cache state (no secrets). Confirms the server is wired correctly."""
    return {
        "base_url": BASE_URL,
        "region": REGION,
        "default_marketplace_id": MARKETPLACE_ID,
        "client_id_set": bool(CLIENT_ID),
        "client_secret_set": bool(CLIENT_SECRET),
        "refresh_token_set": bool(REFRESH_TOKEN),
        "seller_id_cached": _seller_id_cache["value"],
        "token_cached": bool(_token_cache["access_token"]),
        "token_expires_in_seconds": max(0, int(_token_cache["expires_at"] - time.time())),
    }


@mcp.tool()
async def amazon_get_marketplace_participations() -> dict:
    """List marketplaces the seller participates in. Useful for finding the Seller ID."""
    return await _get("/sellers/v1/marketplaceParticipations")


@mcp.tool()
async def amazon_get_orders(
    created_after: str,
    created_before: str | None = None,
    order_statuses: list[str] | None = None,
    marketplace_ids: list[str] | None = None,
    max_results_per_page: int = 50,
    next_token: str | None = None,
) -> dict:
    """Fetch orders since a given timestamp. Mirrors Walmart's get_orders for the sales feed.

    Args:
        created_after: ISO8601, e.g. "2026-05-14T00:00:00Z". Must be at least 2 minutes ago.
        created_before: Optional ISO8601 end timestamp.
        order_statuses: Optional list, e.g. ["Shipped", "Unshipped", "Pending"].
        marketplace_ids: Defaults to [AMAZON_MARKETPLACE_ID].
        max_results_per_page: 1-100.
        next_token: Pagination token from a previous response.
    """
    params: dict[str, Any] = {
        "CreatedAfter": created_after,
        "MarketplaceIds": ",".join(marketplace_ids or [MARKETPLACE_ID]),
        "MaxResultsPerPage": max(1, min(int(max_results_per_page), 100)),
    }
    if created_before:
        params["CreatedBefore"] = created_before
    if order_statuses:
        params["OrderStatuses"] = ",".join(order_statuses)
    if next_token:
        params["NextToken"] = next_token
    return await _get("/orders/v0/orders", params)


@mcp.tool()
async def amazon_get_order(order_id: str) -> dict:
    """Fetch a single order by Amazon Order ID (e.g. 123-1234567-1234567)."""
    if not order_id:
        return {"error": True, "message": "order_id is required"}
    return await _get(f"/orders/v0/orders/{order_id}")


@mcp.tool()
async def amazon_get_order_items(order_id: str, next_token: str | None = None) -> dict:
    """Fetch line items for a single order."""
    if not order_id:
        return {"error": True, "message": "order_id is required"}
    params: dict[str, Any] = {}
    if next_token:
        params["NextToken"] = next_token
    return await _get(f"/orders/v0/orders/{order_id}/orderItems", params or None)


@mcp.tool()
async def amazon_get_fba_inventory(
    seller_skus: list[str] | None = None,
    marketplace_id: str | None = None,
    details: bool = True,
    next_token: str | None = None,
) -> dict:
    """FBA inventory summaries — on-hand, reserved, inbound, researching.

    Args:
        seller_skus: Optional list of SKUs to filter to (up to 50).
        marketplace_id: Defaults to AMAZON_MARKETPLACE_ID.
        details: True for per-condition + per-disposition breakdown.
        next_token: Pagination token.
    """
    mp = marketplace_id or MARKETPLACE_ID
    params: dict[str, Any] = {
        "granularityType": "Marketplace",
        "granularityId": mp,
        "marketplaceIds": mp,
        "details": "true" if details else "false",
    }
    if seller_skus:
        params["sellerSkus"] = ",".join(seller_skus[:50])
    if next_token:
        params["nextToken"] = next_token
    return await _get("/fba/inventory/v1/summaries", params)


@mcp.tool()
async def amazon_search_listings(
    identifiers: list[str] | None = None,
    identifiers_type: str = "SKU",
    marketplace_id: str | None = None,
    included_data: list[str] | None = None,
    page_size: int = 20,
    page_token: str | None = None,
) -> dict:
    """Search/listing items in your catalog (publish state, offers, issues).

    Args:
        identifiers: List of SKUs/ASINs (up to 20). If omitted, returns paginated catalog.
        identifiers_type: "SKU" | "ASIN" | "EAN" | "GTIN" | "ISBN" | "JAN" | "UPC".
        marketplace_id: Defaults to AMAZON_MARKETPLACE_ID.
        included_data: e.g. ["summaries","offers","attributes","issues","fulfillmentAvailability"].
        page_size: 1-20.
        page_token: Pagination token.
    """
    seller_id = await _resolve_seller_id()
    params: dict[str, Any] = {
        "marketplaceIds": marketplace_id or MARKETPLACE_ID,
        "includedData": ",".join(included_data or ["summaries", "offers", "issues"]),
        "pageSize": max(1, min(int(page_size), 20)),
    }
    if identifiers:
        params["identifiers"] = ",".join(identifiers[:20])
        params["identifiersType"] = identifiers_type
    if page_token:
        params["pageToken"] = page_token
    return await _get(f"/listings/2021-08-01/items/{seller_id}", params)


@mcp.tool()
async def amazon_get_listing(
    sku: str,
    marketplace_id: str | None = None,
    included_data: list[str] | None = None,
) -> dict:
    """Fetch a single listing by SKU with publish state, offers, attributes, issues."""
    if not sku:
        return {"error": True, "message": "sku is required"}
    seller_id = await _resolve_seller_id()
    params = {
        "marketplaceIds": marketplace_id or MARKETPLACE_ID,
        "includedData": ",".join(
            included_data
            or ["summaries", "offers", "attributes", "issues", "fulfillmentAvailability"]
        ),
    }
    return await _get(f"/listings/2021-08-01/items/{seller_id}/{sku}", params)


@mcp.tool()
async def amazon_request_report(
    report_type: str,
    data_start_time: str | None = None,
    data_end_time: str | None = None,
    marketplace_ids: list[str] | None = None,
    report_options: dict | None = None,
) -> dict:
    """Kick off a report. Returns a reportId — poll amazon_get_report until processingStatus=DONE.

    Common reportTypes for sales/traffic:
      - GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL (CSV, all orders)
      - GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL (CSV, FBA shipments)
      - GET_SALES_AND_TRAFFIC_REPORT (JSON, Brand Analytics — requires that role)
      - GET_VENDOR_SALES_REPORT (vendor/1P only)
      - GET_FBA_INVENTORY_PLANNING_DATA
      - GET_MERCHANT_LISTINGS_ALL_DATA (full catalog dump)
    """
    body: dict[str, Any] = {
        "reportType": report_type,
        "marketplaceIds": marketplace_ids or [MARKETPLACE_ID],
    }
    if data_start_time:
        body["dataStartTime"] = data_start_time
    if data_end_time:
        body["dataEndTime"] = data_end_time
    if report_options:
        body["reportOptions"] = report_options
    return await _post("/reports/2021-06-30/reports", body)


@mcp.tool()
async def amazon_get_report(report_id: str) -> dict:
    """Check status of a report. When processingStatus=DONE, use reportDocumentId."""
    if not report_id:
        return {"error": True, "message": "report_id is required"}
    return await _get(f"/reports/2021-06-30/reports/{report_id}")


@mcp.tool()
async def amazon_get_report_document(
    report_document_id: str,
    max_chars: int = 50000,
) -> dict:
    """Download + decompress a finished report document. Returns parsed text (truncated).

    Args:
        report_document_id: From amazon_get_report once processingStatus=DONE.
        max_chars: Cap on returned content size — reports can be huge.
    """
    if not report_document_id:
        return {"error": True, "message": "report_document_id is required"}
    meta = await _get(f"/reports/2021-06-30/documents/{report_document_id}")
    if isinstance(meta, dict) and meta.get("error"):
        return meta
    url = meta.get("url")
    if not url:
        return {"error": True, "message": "No url in document metadata", "meta": meta}
    compression = meta.get("compressionAlgorithm")
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(url)
        if r.status_code >= 400:
            return {"error": True, "status": r.status_code, "message": r.text[:500]}
        raw = r.content
    if compression == "GZIP":
        try:
            raw = gzip.decompress(raw)
        except Exception as e:
            return {"error": True, "message": f"gunzip failed: {e}"}
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
    truncated = len(text) > max_chars
    return {
        "documentId": report_document_id,
        "compression": compression,
        "totalChars": len(text),
        "truncated": truncated,
        "content": text[:max_chars],
    }


if __name__ == "__main__":
    mcp.run()
