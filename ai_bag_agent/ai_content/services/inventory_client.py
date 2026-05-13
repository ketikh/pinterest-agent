"""Tissu storefront API client — pulls bag inventory from the existing bot.

The Pinterest agent calls https://tissu-agent-production.up.railway.app/api/products
to discover what bags are currently in stock, so admin no longer has to upload
photos manually for every generation cycle.

Public API:
    health_check() -> bool
    list_products(in_stock_only=True) -> list[dict]
    get_random_in_stock_product(exclude_recent_names=None) -> dict | None
"""

from __future__ import annotations

import logging
import os
import random
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://tissu-agent-production.up.railway.app"
TIMEOUT_SEC = 10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def health_check() -> bool:
    """Verify the storefront API is reachable and the API key is valid."""
    base = _base_url()
    key = _api_key()
    if not key:
        logger.error("STOREFRONT_API_KEY not set")
        return False
    try:
        r = requests.get(
            f"{base}/api/storefront/health",
            headers={"X-API-Key": key},
            timeout=TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        logger.warning("Storefront health-check network error: %s", exc)
        return False
    if r.status_code != 200:
        logger.error("Storefront health-check HTTP %d: %s", r.status_code, r.text[:200])
        return False
    return True


def list_products(in_stock_only: bool = True) -> list:
    """Return the simplified product list from /api/products.

    Each item: {id, name, image_url, in_stock}.
    Returns [] on any failure (logged).
    """
    base = _base_url()
    key = _api_key()
    if not key:
        logger.error("STOREFRONT_API_KEY not set")
        return []

    try:
        r = requests.get(
            f"{base}/api/products",
            headers={"X-API-Key": key},
            timeout=TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        logger.warning("Storefront /api/products network error: %s", exc)
        return []

    if r.status_code == 401 or r.status_code == 403:
        logger.error("Storefront API rejected our key (HTTP %d)", r.status_code)
        return []
    if r.status_code != 200:
        logger.error("Storefront /api/products HTTP %d: %s", r.status_code, r.text[:200])
        return []

    try:
        data = r.json()
    except ValueError:
        logger.error("Storefront /api/products returned non-JSON: %s", r.text[:200])
        return []
    if not isinstance(data, list):
        logger.error("Storefront /api/products returned non-list: %r", data)
        return []

    if in_stock_only:
        data = [p for p in data if p.get("in_stock") is True]
    return data


def get_random_in_stock_product(
    exclude_recent_names: Optional[set] = None,
) -> Optional[dict]:
    """Pick a random in-stock product, optionally avoiding names used recently.

    Returns None when the inventory is empty or every in-stock item is in
    `exclude_recent_names`. The caller can then fall back to all items.
    """
    products = list_products(in_stock_only=True)
    if not products:
        logger.info("Inventory: no in-stock products")
        return None

    if exclude_recent_names:
        fresh = [p for p in products if p.get("name") not in exclude_recent_names]
        if fresh:
            return random.choice(fresh)
        logger.info("Inventory: every in-stock product was used recently — picking anyway")

    return random.choice(products)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _base_url() -> str:
    return os.environ.get("STOREFRONT_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    return os.environ.get("STOREFRONT_API_KEY", "")
