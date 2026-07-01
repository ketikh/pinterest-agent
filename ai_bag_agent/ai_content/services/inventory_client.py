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
    """Return the rich product list from /api/storefront/products.

    Each item exposes the full storefront schema: id, name, code,
    image_front, image_back, category_slug, in_stock, etc. We keep only
    laptop-case products (category_slug "laptop-cases"; excludes necklaces,
    tote-bags, aprons, kids bags). Returns [] on any failure (logged).
    """
    base = _base_url()
    key = _api_key()
    if not key:
        logger.error("STOREFRONT_API_KEY not set")
        return []

    try:
        r = requests.get(
            f"{base}/api/storefront/products",
            headers={"X-API-Key": key},
            timeout=TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        logger.warning("Storefront /api/storefront/products network error: %s", exc)
        return []

    if r.status_code == 401 or r.status_code == 403:
        logger.error("Storefront API rejected our key (HTTP %d)", r.status_code)
        return []
    if r.status_code != 200:
        logger.error("Storefront /api/storefront/products HTTP %d: %s",
                     r.status_code, r.text[:200])
        return []

    try:
        body = r.json()
    except ValueError:
        logger.error("Storefront /api/storefront/products returned non-JSON: %s",
                     r.text[:200])
        return []

    # /api/storefront/products wraps the list in {"products": [...]}, while the
    # legacy /api/products returned a plain list. Accept both.
    if isinstance(body, dict):
        data = body.get("products", [])
    elif isinstance(body, list):
        data = body
    else:
        logger.error("Storefront products unexpected payload: %r", body)
        return []

    if in_stock_only:
        data = [p for p in data if p.get("in_stock") is True]

    # Category filter — only laptop cases. The storefront tags rows by
    # category_slug: 'laptop-cases' (what we want), 'tote-bags', 'necklace',
    # 'apron', 'kidsbag'.
    # Configurable via env to cover future categories without a deploy.
    allowed_slug_raw = os.environ.get("INVENTORY_CATEGORY_SLUGS", "laptop-cases")
    if allowed_slug_raw and allowed_slug_raw.strip() != "*":
        allowed = tuple(s.strip() for s in allowed_slug_raw.split(",") if s.strip())
        before = len(data)
        data = [p for p in data if (p.get("category_slug") or "") in allowed]
        if before != len(data):
            logger.info(
                "Inventory category-filter: kept %d/%d matching slugs %s",
                len(data), before, allowed,
            )

    # Legacy escape hatches (kept for safety, default off):
    #   INVENTORY_NAME_PREFIXES  — include-list by name prefix
    #   INVENTORY_NAME_EXCLUDES  — substring exclude-list
    include_raw = os.environ.get("INVENTORY_NAME_PREFIXES", "*").strip()
    if include_raw and include_raw != "*":
        prefixes = tuple(p.strip() for p in include_raw.split(",") if p.strip())
        if prefixes:
            before = len(data)
            data = [p for p in data if (p.get("name") or "").strip().startswith(prefixes)]
            if before != len(data):
                logger.info(
                    "Inventory include-filter: kept %d/%d matching prefixes %s",
                    len(data), before, prefixes,
                )
        return data

    exclude_raw = os.environ.get("INVENTORY_NAME_EXCLUDES", "")
    excludes = tuple(e.strip() for e in exclude_raw.split(",") if e.strip())
    if excludes:
        before = len(data)
        data = [
            p for p in data
            if not any(ex in (p.get("name") or "") for ex in excludes)
        ]
        if before != len(data):
            logger.info(
                "Inventory exclude-filter: kept %d/%d, dropped names containing %s",
                len(data), before, excludes,
            )
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
