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

    # Filter out known non-laptop-bag products. The storefront mixes bags
    # with necklaces (ყელსაბამი), aprons (წინსაფარი) and child bags
    # (ბავშვის ჩანთა) — we only want laptop bags. Earlier we used an
    # INVENTORY_NAME_PREFIXES include-list defaulting to "Tissu", but the
    # storefront then renamed every bag SKU to a colour/flower name
    # (Olive, Lemon, Lagoon…) which broke that filter silently for days.
    # Excluding the small fixed non-bag set is more robust to renames.
    # Env overrides:
    #   INVENTORY_NAME_EXCLUDES  — comma-separated substrings to exclude
    #                              (default below covers the known non-bags)
    #   INVENTORY_NAME_PREFIXES  — optional include-list (legacy); when set,
    #                              behaves the same as before. Set to "*"
    #                              or leave unset to use the exclude filter.
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

    exclude_raw = os.environ.get(
        "INVENTORY_NAME_EXCLUDES",
        "ყელსაბამი,წინსაფარი,ბავშვის",
    )
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
