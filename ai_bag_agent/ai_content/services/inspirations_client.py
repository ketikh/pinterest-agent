"""Tissu storefront 'inspirations' API client — reference product photos.

The storefront (same host as the inventory API) exposes a gallery of
admin-uploaded reference photos, grouped by category (necklace, …). The
Pinterest agent reads it to discover which necklaces to generate content
for — the necklace analog of how `inventory_client.py` reads bags.

Contract (storefront side):
    GET {base}/api/inspirations[?category=<slug>]
    Header: X-API-Key: <INSPIRATIONS_API_KEY>
    200 → {"photos": [{id, category, image_url, caption, position,
                       created_at}, ...]}

Empty category → all categories. Photos are returned sorted by `position`.

Public API:
    list_inspirations(category=None) -> list[dict]
    get_inspiration(inspiration_id, category=None) -> dict | None
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://tissu-agent-production.up.railway.app"
TIMEOUT_SEC = 10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_inspirations(category: Optional[str] = None) -> list:
    """Return reference photos from /api/inspirations, sorted by position.

    Args:
        category: Optional category slug (e.g. "necklace"). None/empty → all.

    Returns:
        list of dicts: {id, category, image_url, caption, position,
        created_at}. Returns [] on any failure (logged).
    """
    key = _api_key()
    if not key:
        logger.error("INSPIRATIONS_API_KEY (or STOREFRONT_API_KEY) not set")
        return []

    base = _base_url()
    params = {"category": category} if category else None

    try:
        r = requests.get(
            f"{base}/api/inspirations",
            headers={"X-API-Key": key},
            params=params,
            timeout=TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        logger.warning("Inspirations /api/inspirations network error: %s", exc)
        return []

    if r.status_code in (401, 403):
        logger.error(
            "Inspirations API rejected our key (HTTP %d) — check INSPIRATIONS_API_KEY",
            r.status_code,
        )
        return []
    if r.status_code != 200:
        logger.error("Inspirations /api/inspirations HTTP %d: %s",
                     r.status_code, r.text[:200])
        return []

    try:
        body = r.json()
    except ValueError:
        logger.error("Inspirations /api/inspirations returned non-JSON: %s", r.text[:200])
        return []

    # Accept both {"photos": [...]} and a bare list, mirroring inventory_client.
    if isinstance(body, dict):
        photos = body.get("photos", [])
    elif isinstance(body, list):
        photos = body
    else:
        logger.error("Inspirations unexpected payload: %r", body)
        return []

    if not isinstance(photos, list):
        logger.error("Inspirations 'photos' is not a list: %r", photos)
        return []

    # Keep only rows with a usable image_url, then sort by position so the
    # admin sees them in the order curated on the storefront.
    photos = [p for p in photos if isinstance(p, dict) and p.get("image_url")]
    photos.sort(key=lambda p: _position_key(p.get("position")))
    return photos


def get_inspiration(
    inspiration_id: int, category: Optional[str] = None
) -> Optional[dict]:
    """Return a single inspiration row by id, or None if not found."""
    for photo in list_inspirations(category=category):
        if str(photo.get("id")) == str(inspiration_id):
            return photo
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _position_key(position) -> tuple:
    """Sort key that tolerates missing / non-numeric positions (push to end)."""
    try:
        return (0, int(position))
    except (TypeError, ValueError):
        return (1, 0)


def _base_url() -> str:
    return os.environ.get("STOREFRONT_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    # Dedicated key for the inspirations gallery; fall back to the inventory
    # key since both live on the same storefront host.
    return os.environ.get("INSPIRATIONS_API_KEY") or os.environ.get("STOREFRONT_API_KEY", "")
