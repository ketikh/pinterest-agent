"""Pinterest API v5 client.

Flow:
  1. GET /v5/boards/{board_id}/pins  → list of pins (paginated, up to 250)
  2. Filter out recently-used pins   → RecentPinCache (7-day window)
  3. Pick random pin                 → PinData
  4. Mark pin as used                → RecentPinCache

Token refresh:
  - Access token expires every 24h (trial) / 60 days (approved)
  - refresh_access_token() exchanges PINTEREST_REFRESH_TOKEN for a new
    access token and updates PINTEREST_ACCESS_TOKEN in DB settings
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PINTEREST_API = "https://api.pinterest.com/v5"
PINTEREST_TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"

# Largest image size preferred for kie.ai compatibility (must be JPG)
_IMAGE_SIZE_PREFERENCE = ["1200x", "736x", "600x", "400x300", "150x150"]

RECENT_CACHE_DAYS = int(os.environ.get("RECENT_PIN_CACHE_DAYS", "7"))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PinData:
    pin_id: str
    image_url: str   # public HTTPS JPG URL
    title: str
    description: str
    pin_url: str


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_random_reference_pin(
    board_id: str,
    tenant_id: str = "default",
    exclude_recent: bool = True,
) -> Optional[PinData]:
    """Return a random pin from the board, avoiding recently-used ones.

    Args:
        board_id: Pinterest board ID.
        tenant_id: Tenant identifier (used for cache isolation).
        exclude_recent: If True, skip pins used within RECENT_PIN_CACHE_DAYS.

    Returns:
        PinData or None if no suitable pin found.
    """
    token = _get_access_token()
    if not token:
        logger.error("Pinterest access token not configured")
        return None

    pins = _fetch_board_pins(board_id, token)
    if not pins:
        logger.warning("No pins returned from board %s", board_id)
        return None

    if exclude_recent:
        recent_ids = _get_recent_pin_ids(tenant_id)
        pins = [p for p in pins if p["id"] not in recent_ids]

    if not pins:
        logger.warning("All pins recently used for tenant=%s — resetting cache", tenant_id)
        _clear_pin_cache(tenant_id)
        pins = _fetch_board_pins(board_id, token)

    if not pins:
        return None

    chosen = random.choice(pins)
    image_url = _extract_image_url(chosen)
    if not image_url:
        logger.warning("Pin %s has no usable image URL", chosen.get("id"))
        return None

    pin_data = PinData(
        pin_id=chosen["id"],
        image_url=image_url,
        title=chosen.get("title") or "",
        description=chosen.get("description") or "",
        pin_url=f"https://www.pinterest.com/pin/{chosen['id']}/",
    )

    _mark_pin_used(pin_data.pin_id, tenant_id)
    logger.info("Pinterest pin selected: %s", pin_data.pin_id)
    return pin_data


def refresh_access_token() -> Optional[str]:
    """Use PINTEREST_REFRESH_TOKEN to get a new access token.

    Returns:
        New access token string, or None on failure.
    """
    refresh_token = os.environ.get("PINTEREST_REFRESH_TOKEN")
    app_id = os.environ.get("PINTEREST_APP_ID")
    app_secret = os.environ.get("PINTEREST_APP_SECRET")

    if not all([refresh_token, app_id, app_secret]):
        logger.error(
            "Cannot refresh Pinterest token — "
            "PINTEREST_REFRESH_TOKEN, PINTEREST_APP_ID, or PINTEREST_APP_SECRET missing"
        )
        return None

    try:
        resp = requests.post(
            PINTEREST_TOKEN_URL,
            auth=(app_id, app_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "boards:read,pins:read",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error("Pinterest token refresh request failed: %s", exc)
        return None

    if resp.status_code != 200:
        logger.error("Pinterest token refresh HTTP %d: %s", resp.status_code, resp.text[:200])
        return None

    body = resp.json()
    new_token = body.get("access_token")
    if not new_token:
        logger.error("Pinterest token refresh response has no access_token: %s", body)
        return None

    os.environ["PINTEREST_ACCESS_TOKEN"] = new_token
    _save_token_to_db(new_token, body.get("refresh_token"), body.get("expires_in"))

    logger.info("Pinterest access token refreshed successfully")
    return new_token


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_access_token() -> Optional[str]:
    token = os.environ.get("PINTEREST_ACCESS_TOKEN")
    if token:
        return token
    # Try DB settings as fallback
    try:
        from ..models import Setting
        return Setting.get("pinterest_access_token")
    except Exception:
        return None


def _fetch_board_pins(board_id: str, token: str, max_pins: int = 250) -> list:
    """Fetch up to max_pins from the board using cursor-based pagination."""
    headers = {"Authorization": f"Bearer {token}"}
    pins: list = []
    cursor: Optional[str] = None

    while len(pins) < max_pins:
        params: dict = {"page_size": 50}
        if cursor:
            params["bookmark"] = cursor

        try:
            resp = requests.get(
                f"{PINTEREST_API}/boards/{board_id}/pins",
                headers=headers,
                params=params,
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning("Pinterest board pins request failed: %s", exc)
            break

        if resp.status_code == 401:
            logger.error("Pinterest token unauthorized — needs refresh")
            break

        if resp.status_code != 200:
            logger.warning("Pinterest API HTTP %d for board %s", resp.status_code, board_id)
            break

        body = resp.json()
        items = body.get("items", [])
        pins.extend(items)

        cursor = body.get("bookmark")
        if not cursor or not items:
            break

    logger.debug("Fetched %d pins from board %s", len(pins), board_id)
    return pins


def _extract_image_url(pin: dict) -> Optional[str]:
    """Extract the best available image URL from a pin object, as JPG."""
    images = (pin.get("media") or {}).get("images") or {}
    for size in _IMAGE_SIZE_PREFERENCE:
        entry = images.get(size)
        if entry and entry.get("url"):
            return _to_jpg_url(entry["url"])
    return None


def _to_jpg_url(url: str) -> str:
    """Convert Pinterest WebP URL to JPG equivalent."""
    # webp70/1200x/XX/XX/XX/hash.webp  →  736x/XX/XX/XX/hash.jpg
    url = re.sub(r"/webp\d+/\d+x/", "/736x/", url)
    url = re.sub(r"\.webp$", ".jpg", url)
    return url


def _get_recent_pin_ids(tenant_id: str) -> set:
    """Return set of pin_ids used within the cache window."""
    try:
        from ..models import RecentPinCache
        from ...extensions import db
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_CACHE_DAYS)
        rows = (
            db.session.query(RecentPinCache.pin_id)
            .filter(
                RecentPinCache.tenant_id == tenant_id,
                RecentPinCache.used_at >= cutoff,
            )
            .all()
        )
        return {r.pin_id for r in rows}
    except Exception as exc:
        logger.debug("Could not query RecentPinCache (no app context?): %s", exc)
        return set()


def _mark_pin_used(pin_id: str, tenant_id: str) -> None:
    """Insert or update pin usage in RecentPinCache."""
    try:
        from ..models import RecentPinCache
        from ...extensions import db
        existing = (
            db.session.query(RecentPinCache)
            .filter_by(pin_id=pin_id, tenant_id=tenant_id)
            .first()
        )
        if existing:
            existing.used_at = datetime.now(timezone.utc)
        else:
            db.session.add(RecentPinCache(pin_id=pin_id, tenant_id=tenant_id))
        db.session.commit()
    except Exception as exc:
        logger.debug("Could not mark pin as used (no app context?): %s", exc)


def _clear_pin_cache(tenant_id: str) -> None:
    """Remove all cache entries for a tenant (reset variety control)."""
    try:
        from ..models import RecentPinCache
        from ...extensions import db
        db.session.query(RecentPinCache).filter_by(tenant_id=tenant_id).delete()
        db.session.commit()
        logger.info("Cleared pin cache for tenant=%s", tenant_id)
    except Exception as exc:
        logger.debug("Could not clear pin cache: %s", exc)


def _save_token_to_db(
    access_token: str,
    refresh_token: Optional[str],
    expires_in: Optional[int],
) -> None:
    """Persist refreshed tokens to DB settings table."""
    try:
        from ..models import Setting
        Setting.set("pinterest_access_token", access_token)
        if refresh_token:
            Setting.set("pinterest_refresh_token", refresh_token)
        if expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            Setting.set("pinterest_token_expires_at", expires_at.isoformat())
    except Exception as exc:
        logger.debug("Could not save token to DB: %s", exc)
