"""Pinterest API v5 client.

Token strategy:
  Trial mode  — 24h access token, manual regeneration.
                If token is expired, functions return {"success": False,
                "error": "Token expired..."} so admin sees it clearly.
  Production  — PINTEREST_REFRESH_TOKEN in .env → auto-refresh before expiry.
                Refreshed token is persisted to DB settings table.

Board ID resolution:
  PINTEREST_BOARD_URL (env) is resolved to a numeric board_id once,
  then cached in DB settings so repeated calls skip the API lookup.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pinterest.com/v5"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"

_IMAGE_SIZE_PREFERENCE = ["1200x", "originals", "736x", "564x", "236x"]

# Default to a very long window so every used pin stays excluded until we've
# cycled through the entire board at least once. get_random_pin automatically
# resets the cache when no fresh pins remain, so this large value just means
# "never repeat until exhausted". Override via RECENT_PIN_CACHE_DAYS env.
RECENT_CACHE_DAYS = int(os.environ.get("RECENT_PIN_CACHE_DAYS", "365"))

# ---------------------------------------------------------------------------
# Public: board discovery
# ---------------------------------------------------------------------------


def get_user_boards(tenant_id: str = "default") -> list:
    """GET /v5/boards — returns list of user's boards.

    Returns:
        list of dicts: {id, name, url, pin_count, privacy}
    """
    token = _get_token()
    if not token:
        logger.error("Pinterest token not configured")
        return []

    headers = _headers(token)
    boards = []
    bookmark = None

    while True:
        params = {"page_size": 25}
        if bookmark:
            params["bookmark"] = bookmark

        resp = _get(f"{BASE_URL}/boards", headers=headers, params=params)
        if resp is None:
            break

        data = resp.json()
        for b in data.get("items", []):
            boards.append({
                "id": b["id"],
                "name": b.get("name", ""),
                "url": b.get("url", ""),
                "pin_count": b.get("pin_count", 0),
                "privacy": b.get("privacy", ""),
            })

        bookmark = data.get("bookmark")
        if not bookmark:
            break

    return boards


def get_board_id_from_url(board_url: str, tenant_id: str = "default") -> Optional[str]:
    """Resolve a Pinterest board URL to its numeric board ID.

    Strategy:
      1. Check DB settings cache (key: pinterest_board_id:{board_url})
      2. Parse URL → owner/slug
      3. GET /v5/boards → match by url or slug
      4. Cache result in DB settings

    Returns:
        board_id string or None if not found.
    """
    cache_key = f"pinterest_board_id:{board_url}"
    cached = _settings_get(cache_key)
    if cached:
        logger.debug("Board ID from cache: %s → %s", board_url, cached)
        return cached

    slug = _slug_from_url(board_url)              # e.g. "tissugeorgia/laptop-bags"
    url_tail = (slug.split("/")[-1] if slug else "")  # e.g. "laptop-bags"
    boards = get_user_boards(tenant_id)

    for board in boards:
        # 1. Full URL match
        if board.get("url", "").rstrip("/") == board_url.rstrip("/"):
            _settings_set(cache_key, board["id"])
            return board["id"]
        # 2. Slug match from board.url (when API returns it)
        board_slug = _slug_from_url(board.get("url", ""))
        if slug and board_slug and slug == board_slug:
            _settings_set(cache_key, board["id"])
            return board["id"]
        # 3. Fallback: Pinterest v5 sometimes returns empty board.url, so
        #    slugify board.name ("Laptop Bags" → "laptop-bags") and compare
        #    against the URL's last path segment.
        name_slug = _slugify(board.get("name", ""))
        if url_tail and name_slug and url_tail == name_slug:
            _settings_set(cache_key, board["id"])
            return board["id"]

    logger.error(
        "Board not found for URL: %s — available: %s",
        board_url,
        [(b.get("name"), b.get("url") or "(empty)") for b in boards],
    )
    return None


# ---------------------------------------------------------------------------
# Public: pins
# ---------------------------------------------------------------------------

def get_pins_from_board(board_id: str, page_size: int = 25) -> list:
    """GET /v5/boards/{board_id}/pins — returns all pins (paginated).

    Returns:
        list of raw pin dicts from Pinterest API.
    """
    token = _get_token()
    if not token:
        return []

    headers = _headers(token)
    pins = []
    bookmark = None

    while True:
        params = {"page_size": min(page_size, 25)}
        if bookmark:
            params["bookmark"] = bookmark

        resp = _get(f"{BASE_URL}/boards/{board_id}/pins", headers=headers, params=params)
        if resp is None:
            break

        data = resp.json()
        pins.extend(data.get("items", []))

        bookmark = data.get("bookmark")
        if not bookmark or not data.get("items"):
            break

    logger.debug("Fetched %d pins from board %s", len(pins), board_id)
    return pins


def get_random_pin(
    board_url: str,
    tenant_id: str = "default",
    exclude_recent_days: int = RECENT_CACHE_DAYS,
) -> dict:
    """Main function used by the orchestrator.

    Returns:
        {success, pin_id, image_url, pin_url, alt_text, error}
    """
    token = _get_token()
    if not token:
        return _err("Pinterest token not set — add PINTEREST_ACCESS_TOKEN to .env")

    # Resolve board URL → board ID
    board_id = get_board_id_from_url(board_url, tenant_id)
    if not board_id:
        return _err(f"Could not resolve board ID from: {board_url}")

    # Fetch pins
    pins = get_pins_from_board(board_id)
    if not pins:
        return _err("Board has no pins or token expired")

    # Rotate references robustly: prefer pins that were NEVER used (newest
    # first), then the LEAST-recently-used. "Used" is read from approvals'
    # reference_pin_id (which always persists) plus the recent-pin cache — so
    # rotation keeps working even if a cache write was skipped. No repeat until
    # every pin has been shown, then oldest-first.
    last_used = get_pin_last_used_map(tenant_id)
    never_used = [p for p in pins if p["id"] not in last_used]
    if never_used:
        never_used.sort(key=lambda p: (p.get("created_at") or ""), reverse=True)
        ordered = never_used
    else:
        ordered = sorted(pins, key=lambda p: last_used.get(p["id"], 0.0))

    chosen = None
    image_url = None
    for candidate in ordered:
        try:
            image_url = get_best_image_url(candidate)
        except ValueError:
            continue
        chosen = candidate
        break

    if chosen is None:
        return _err("No pin with a usable image URL on the board")

    pin_id = chosen["id"]
    # Convert WebP to JPG for kie.ai compatibility
    image_url = _to_jpg_url(image_url)

    mark_pin_as_used(pin_id, tenant_id)

    return {
        "success": True,
        "pin_id": pin_id,
        "image_url": image_url,
        "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
        "alt_text": chosen.get("description") or chosen.get("title") or None,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Public: image URL helper
# ---------------------------------------------------------------------------

def get_best_image_url(pin: dict) -> str:
    """Return the highest-resolution image URL available for a pin."""
    images = (pin.get("media") or {}).get("images") or {}
    for size in _IMAGE_SIZE_PREFERENCE:
        entry = images.get(size)
        if entry and entry.get("url"):
            return entry["url"]
    raise ValueError(f"No image URL found in pin {pin.get('id')}")


# ---------------------------------------------------------------------------
# Public: recent pin cache
# ---------------------------------------------------------------------------

def get_recent_pin_ids(tenant_id: str, days: int = RECENT_CACHE_DAYS) -> set:
    """Return set of pin_ids used within the last N days."""
    try:
        from ..models import RecentPinCache
        from ...extensions import db
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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
        logger.debug("RecentPinCache query skipped (no app context?): %s", exc)
        return set()


def _to_epoch(dt) -> float:
    """Datetime → epoch seconds, tolerating naive datetimes and None."""
    if dt is None:
        return 0.0
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def get_pin_last_used_map(tenant_id: str, limit: int = 1000) -> dict:
    """Map pin_id → most-recent-use epoch seconds.

    Sourced from approvals' reference_pin_id (durable — approvals always
    persist) and the recent-pin cache. Used to rotate references reliably.
    """
    from ...extensions import db
    out: dict = {}
    try:
        from ..models import PendingApproval
        rows = (
            db.session.query(
                PendingApproval.reference_pin_id, PendingApproval.created_at
            )
            .filter(
                PendingApproval.tenant_id == tenant_id,
                PendingApproval.reference_pin_id.isnot(None),
            )
            .order_by(PendingApproval.created_at.desc())
            .limit(limit)
            .all()
        )
        for pid, created in rows:
            if pid and pid not in out:  # first row = most recent
                out[pid] = _to_epoch(created)
    except Exception as exc:
        logger.debug("last-used (approvals) skipped: %s", exc)
    try:
        from ..models import RecentPinCache
        rows = (
            db.session.query(RecentPinCache.pin_id, RecentPinCache.used_at)
            .filter(RecentPinCache.tenant_id == tenant_id)
            .all()
        )
        for pid, used in rows:
            e = _to_epoch(used)
            if pid and e > out.get(pid, 0.0):
                out[pid] = e
    except Exception as exc:
        logger.debug("last-used (cache) skipped: %s", exc)
    return out


def mark_pin_as_used(pin_id: str, tenant_id: str) -> None:
    """Insert or refresh pin usage in recent_pin_cache (best-effort; approvals'
    reference_pin_id is the durable fallback for rotation)."""
    from ...extensions import db
    try:
        from ..models import RecentPinCache
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
        # Retry once on a clean session — the pipeline session may be in a
        # failed transaction state at this point.
        logger.warning("mark_pin_as_used failed for %s (%s) — retrying clean",
                       pin_id, exc)
        try:
            db.session.rollback()
            db.session.add(RecentPinCache(pin_id=pin_id, tenant_id=tenant_id))
            db.session.commit()
        except Exception as exc2:
            logger.error("mark_pin_as_used retry failed for %s: %s", pin_id, exc2)
            try:
                db.session.rollback()
            except Exception:
                pass


def cleanup_old_cache(tenant_id: str = "default", days: int = 30) -> int:
    """Delete cache entries older than N days. Returns deleted count."""
    try:
        from ..models import RecentPinCache
        from ...extensions import db
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = (
            db.session.query(RecentPinCache)
            .filter(
                RecentPinCache.tenant_id == tenant_id,
                RecentPinCache.used_at < cutoff,
            )
            .delete()
        )
        db.session.commit()
        logger.info("Cleaned %d old pin cache entries for tenant=%s", deleted, tenant_id)
        return deleted
    except Exception as exc:
        logger.debug("cleanup_old_cache skipped: %s", exc)
        return 0


def clear_board_pins_from_cache(pin_ids: set, tenant_id: str = "default") -> int:
    """Remove only the given pin_ids from the recent cache (scoped board reset).

    Lets one board cycle back to the start without touching other boards'
    recent-use history. Returns the number of rows deleted.
    """
    if not pin_ids:
        return 0
    try:
        from ..models import RecentPinCache
        from ...extensions import db
        deleted = (
            db.session.query(RecentPinCache)
            .filter(
                RecentPinCache.tenant_id == tenant_id,
                RecentPinCache.pin_id.in_(list(pin_ids)),
            )
            .delete(synchronize_session=False)
        )
        db.session.commit()
        logger.info("Reset %d cached pins for one board (tenant=%s)", deleted, tenant_id)
        return deleted
    except Exception as exc:
        logger.debug("clear_board_pins_from_cache skipped: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Token refresh (production)
# ---------------------------------------------------------------------------

def refresh_access_token() -> Optional[str]:
    """Exchange PINTEREST_REFRESH_TOKEN for a new access token.

    Trial mode: not used (tokens refreshed manually).
    Production: called automatically when token is near expiry.
    """
    refresh_token = os.environ.get("PINTEREST_REFRESH_TOKEN")
    app_id = os.environ.get("PINTEREST_APP_ID")
    app_secret = os.environ.get("PINTEREST_APP_SECRET")

    if not all([refresh_token, app_id, app_secret]):
        logger.error(
            "Cannot refresh token — PINTEREST_REFRESH_TOKEN / APP_ID / APP_SECRET missing"
        )
        return None

    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(app_id, app_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "boards:read,pins:read",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error("Token refresh request failed: %s", exc)
        return None

    if resp.status_code != 200:
        logger.error("Token refresh HTTP %d: %s", resp.status_code, resp.text[:200])
        return None

    body = resp.json()
    new_token = body.get("access_token")
    if not new_token:
        return None

    os.environ["PINTEREST_ACCESS_TOKEN"] = new_token
    _settings_set("pinterest_access_token", new_token)
    if body.get("refresh_token"):
        os.environ["PINTEREST_REFRESH_TOKEN"] = body["refresh_token"]
        _settings_set("pinterest_refresh_token", body["refresh_token"])

    expires_in = body.get("expires_in", 86400)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    _settings_set("pinterest_token_expires_at", expires_at.isoformat())

    logger.info("Pinterest access token refreshed, expires %s", expires_at.isoformat())
    return new_token


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_token(tenant_id: str = "default") -> Optional[str]:
    """Return a usable Pinterest access token.

    Order:
      1. OAuth flow (pinterest_oauth.get_valid_access_token) — auto-refreshes
         when the stored token is nearing expiry.
      2. Legacy: PINTEREST_ACCESS_TOKEN env var (24h trial token, manual).
    """
    try:
        from .pinterest_oauth import get_valid_access_token
        token = get_valid_access_token(tenant_id)
        if token:
            return token
    except Exception:
        logger.debug("pinterest_oauth lookup failed; falling back to env/settings",
                     exc_info=True)
    return os.environ.get("PINTEREST_ACCESS_TOKEN") or _settings_get("pinterest_access_token")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get(url: str, headers: dict, params: dict = None, retries: int = 3) -> Optional[requests.Response]:
    """GET with retry on 429 and 5xx. Returns None on unrecoverable error."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as exc:
            logger.warning("Pinterest GET error (attempt %d/%d): %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            return resp

        if resp.status_code == 401:
            logger.error(
                "Pinterest token expired or invalid. "
                "Trial token: regenerate manually at developers.pinterest.com"
            )
            return None

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            logger.warning("Pinterest rate limited — waiting %ds", wait)
            time.sleep(wait)
            continue

        if resp.status_code >= 500 and attempt < retries:
            wait = 2 ** attempt
            logger.warning("Pinterest %d (attempt %d/%d) — retrying in %ds",
                           resp.status_code, attempt, retries, wait)
            time.sleep(wait)
            continue

        logger.error("Pinterest HTTP %d for %s: %s", resp.status_code, url, resp.text[:200])
        return None

    return None


def _slug_from_url(url: str) -> Optional[str]:
    """Extract 'username/board-slug' from a Pinterest board URL."""
    url = url.rstrip("/")
    m = re.search(r"pinterest\.com/([^/]+/[^/]+)$", url)
    return m.group(1) if m else None


def _slugify(name: str) -> str:
    """Convert a Pinterest board name to its URL slug.

    Pinterest's web URLs are lowercased, spaces become dashes, and most
    punctuation drops. "Laptop Bags" → "laptop-bags".
    """
    if not name:
        return ""
    s = name.lower().strip()
    # Collapse any non-alphanumeric run into a single dash
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _to_jpg_url(url: str) -> str:
    """Convert Pinterest WebP URL to JPG."""
    url = re.sub(r"/webp\d+/\d+x/", "/736x/", url)
    url = re.sub(r"\.webp$", ".jpg", url)
    return url


def _settings_get(key: str) -> Optional[str]:
    try:
        from ..models import Setting
        return Setting.get(key)
    except Exception:
        return None


def _settings_set(key: str, value: str) -> None:
    try:
        from ..models import Setting
        Setting.set(key, value)
    except Exception:
        pass


def _err(message: str) -> dict:
    logger.error("Pinterest client error: %s", message)
    return {
        "success": False,
        "pin_id": None,
        "image_url": None,
        "pin_url": None,
        "alt_text": None,
        "error": message,
    }
