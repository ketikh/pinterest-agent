"""Pinterest OAuth 2.0 flow — replaces the manual 24h test token.

Token storage (per tenant) lives in the `Setting` table as three keys:
    pinterest_access_token        — 30-day access token
    pinterest_refresh_token       — 1-year refresh token
    pinterest_token_expires_at    — ISO-8601 timestamp

Public entry points:
    get_authorization_url(state)    — build the URL the admin visits in browser
    exchange_code_for_tokens(code)  — used by scripts/pinterest_login.py callback
    refresh_if_needed(tenant_id)    — auto-renew when near expiry
    get_valid_access_token(tenant_id) — main accessor for pinterest_client.py
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"

# Scopes match the API surface pinterest_client.py touches today.
DEFAULT_SCOPES = "boards:read,pins:read,user_accounts:read"

# Refresh when fewer than this many days remain on the access token.
REFRESH_BEFORE_DAYS = 1


# ---------------------------------------------------------------------------
# Token storage helpers
# ---------------------------------------------------------------------------

def _setting_get(key: str, tenant_id: str = "default") -> Optional[str]:
    try:
        from ..models import Setting
        return Setting.get(key, tenant_id=tenant_id) or None
    except Exception:
        return None


def _setting_set(key: str, value: str, tenant_id: str = "default") -> None:
    try:
        from ..models import Setting
        Setting.set(key, value, tenant_id=tenant_id)
    except Exception:
        logger.exception("Could not persist Pinterest setting %s", key)


def _save_tokens(
    access_token: str,
    refresh_token: Optional[str],
    expires_in: int,
    tenant_id: str = "default",
) -> None:
    """Persist a fresh token pair to Settings."""
    _setting_set("pinterest_access_token", access_token, tenant_id)
    if refresh_token:
        _setting_set("pinterest_refresh_token", refresh_token, tenant_id)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    _setting_set("pinterest_token_expires_at", expires_at.isoformat(), tenant_id)
    logger.info("Pinterest tokens saved — expires %s", expires_at.isoformat())


def _stored_expiry(tenant_id: str = "default") -> Optional[datetime]:
    raw = _setting_get("pinterest_token_expires_at", tenant_id)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        logger.warning("Bad pinterest_token_expires_at value: %r", raw)
        return None


# ---------------------------------------------------------------------------
# Public: authorization URL
# ---------------------------------------------------------------------------

def get_authorization_url(state: str, scope: str = DEFAULT_SCOPES) -> str:
    """Build the Pinterest auth URL the admin opens in their browser."""
    app_id = os.environ.get("PINTEREST_APP_ID")
    redirect_uri = os.environ.get(
        "PINTEREST_REDIRECT_URI", "http://localhost:8080/oauth/callback",
    )
    if not app_id:
        raise RuntimeError("PINTEREST_APP_ID is required")
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Public: code → tokens (one-time, in CLI helper)
# ---------------------------------------------------------------------------

def exchange_code_for_tokens(code: str, tenant_id: str = "default") -> dict:
    """Exchange an authorization code for access + refresh tokens.

    Returns:
        {success, access_token, refresh_token, expires_in, error}
    """
    app_id = os.environ.get("PINTEREST_APP_ID")
    app_secret = os.environ.get("PINTEREST_APP_SECRET")
    redirect_uri = os.environ.get(
        "PINTEREST_REDIRECT_URI", "http://localhost:8080/oauth/callback",
    )
    if not all([app_id, app_secret]):
        return {"success": False, "error": "PINTEREST_APP_ID or PINTEREST_APP_SECRET missing"}

    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(app_id, app_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"success": False, "error": f"network: {exc}"}

    if resp.status_code != 200:
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    body = resp.json()
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in", 2592000)  # default 30 days
    if not access_token:
        return {"success": False, "error": f"response missing access_token: {body}"}

    _save_tokens(access_token, refresh_token, expires_in, tenant_id=tenant_id)
    return {
        "success": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Public: refresh
# ---------------------------------------------------------------------------

def refresh_access_token(tenant_id: str = "default") -> dict:
    """Use the stored refresh_token to mint a new access_token."""
    refresh_token = _setting_get("pinterest_refresh_token", tenant_id) \
        or os.environ.get("PINTEREST_REFRESH_TOKEN")
    app_id = os.environ.get("PINTEREST_APP_ID")
    app_secret = os.environ.get("PINTEREST_APP_SECRET")
    if not all([refresh_token, app_id, app_secret]):
        return {"success": False,
                "error": "PINTEREST_REFRESH_TOKEN / APP_ID / APP_SECRET missing"}

    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(app_id, app_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": DEFAULT_SCOPES,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"success": False, "error": f"network: {exc}"}

    if resp.status_code != 200:
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    body = resp.json()
    access_token = body.get("access_token")
    new_refresh = body.get("refresh_token")  # may rotate
    expires_in = body.get("expires_in", 2592000)
    if not access_token:
        return {"success": False, "error": f"response missing access_token: {body}"}

    _save_tokens(access_token, new_refresh or refresh_token, expires_in, tenant_id=tenant_id)
    return {"success": True, "access_token": access_token, "expires_in": expires_in,
            "error": None}


def refresh_if_needed(tenant_id: str = "default") -> bool:
    """Refresh the access token when fewer than REFRESH_BEFORE_DAYS remain.

    Returns True if a refresh was performed (or no refresh needed and token
    is valid), False if refresh failed and the caller should treat the
    token as unavailable.
    """
    expires_at = _stored_expiry(tenant_id)
    if expires_at is None:
        # No persisted token — nothing to refresh, caller will fall back.
        return False
    if expires_at > datetime.now(timezone.utc) + timedelta(days=REFRESH_BEFORE_DAYS):
        return True  # still fresh enough
    logger.info("Pinterest access token nearing expiry — refreshing")
    result = refresh_access_token(tenant_id)
    if not result["success"]:
        logger.error("Pinterest token refresh failed: %s", result["error"])
        return False
    return True


# ---------------------------------------------------------------------------
# Public: main accessor
# ---------------------------------------------------------------------------

def get_valid_access_token(tenant_id: str = "default") -> Optional[str]:
    """Return a usable Pinterest access token, refreshing if it's expiring.

    Resolution order:
      1. Stored access_token (auto-refresh if near expiry)
      2. PINTEREST_ACCESS_TOKEN env var (legacy / first-time setup)
    """
    refresh_if_needed(tenant_id)
    token = _setting_get("pinterest_access_token", tenant_id)
    if token:
        return token
    return os.environ.get("PINTEREST_ACCESS_TOKEN")
