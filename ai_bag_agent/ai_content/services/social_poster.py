"""Social poster — Facebook Page + Instagram Business via Meta Graph API.

Functions:
    post_to_facebook(image_url, caption, tenant_id) → {success, post_id, error}
    post_to_instagram(image_url, caption, tenant_id) → {success, post_id, error}
    post_to_both(approval_id, tenant_id) → orchestrator, writes PostLog row
    generate_caption(approval, platform) → str (DB Setting override > hardcoded default)
    check_token() → {valid, expires_in_days, name, error}

Status policy (partial-success):
    Both succeed       → approval.status = "posted", PostLog.fb_status = ig_status = "success"
    One succeeds       → approval.status = "posted", failed one recorded in PostLog
    Both fail          → approval.status stays "approved" (next-day retry)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# --- Configuration -----------------------------------------------------------

META_API_VERSION = os.environ.get("META_API_VERSION", "v21.0")
META_GRAPH_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

IG_CONTAINER_POLL_INTERVAL_SEC = 2
IG_CONTAINER_POLL_MAX_SEC = 30
HTTP_TIMEOUT_SEC = 30
MAX_RETRIES = 3

# Hardcoded defaults — overridable via Setting('fb_caption_template' / 'ig_caption_template')
# Admin asked for emoji-only captions: no bag name, no link, no marketing text.
DEFAULT_FB_TEMPLATE = "{emoji}"
DEFAULT_IG_TEMPLATE = "{emoji}"

# Keyword → emoji map. Used as a default decoration when admin didn't write
# a caption — picks something tonally appropriate from the bag's name.
_BAG_EMOJI_RULES = (
    (("leather", "ტყავ"), "🤎"),
    (("black", "შავ"), "🖤"),
    (("white", "თეთრ"), "🤍"),
    (("red", "წითელ"), "❤️"),
    (("blue", "ცისფ", "ლურჯ"), "💙"),
    (("green", "მწვან"), "💚"),
    (("gold", "ოქრო"), "💛"),
    (("silver", "ვერცხლ"), "🤍"),
    (("evening", "night", "საღამო"), "🌙"),
    (("flower", "rose", "ყვავ"), "🌸"),
    (("laptop", "ლეპტოპ", "office"), "💼"),
    (("tote", "შოპერ", "shopper"), "👜"),
    (("cross", "კროს", "messenger"), "👜"),
    (("clutch", "კლათჩ"), "✨"),
)


def pick_emoji_for_bag(bag_name: str) -> str:
    """Pick a thematic emoji based on keywords in the bag name. ✨ is the fallback."""
    if not bag_name:
        return "✨"
    name = bag_name.lower()
    for keywords, emoji in _BAG_EMOJI_RULES:
        if any(kw in name for kw in keywords):
            return emoji
    return "✨"


# ---------------------------------------------------------------------------
# Public: orchestrator
# ---------------------------------------------------------------------------

def post_to_both(approval_id: int, tenant_id: str = "default") -> dict:
    """Post an approval to FB + IG, write PostLog, update approval status.

    Returns:
        dict: {success, fb_status, ig_status, fb_post_id, ig_post_id,
               post_log_id, error}
    """
    from ..models import PendingApproval, PostLog
    from ...extensions import db

    approval = db.session.get(PendingApproval, approval_id)
    if approval is None:
        return _err("Approval not found")
    if approval.status != "approved":
        return _err(f"Approval status is '{approval.status}', not 'approved'")
    if not approval.generated_image_url:
        return _err("Approval has no generated_image_url")

    # Prefer admin-curated AI captions stored on the approval; fall back to
    # the templated default when the AI generation failed or admin cleared.
    fb_caption = approval.fb_caption or generate_caption(approval, platform="fb")
    ig_caption = approval.ig_caption or generate_caption(approval, platform="ig")
    image_url = approval.generated_image_url

    fb_result = post_to_facebook(image_url, fb_caption, tenant_id)
    ig_result = post_to_instagram(image_url, ig_caption, tenant_id)

    log = PostLog(
        tenant_id=tenant_id,
        approval_id=approval_id,
        fb_status="success" if fb_result["success"] else "failed",
        fb_post_id=fb_result.get("post_id"),
        fb_error=fb_result.get("error"),
        ig_status="success" if ig_result["success"] else "failed",
        ig_post_id=ig_result.get("post_id"),
        ig_error=ig_result.get("error"),
        caption=fb_caption,  # store FB caption as canonical (closer to product text)
    )
    db.session.add(log)

    if fb_result["success"] or ig_result["success"]:
        approval.status = "posted"
        approval.responded_at = datetime.now(timezone.utc)
        # bag also moves to "done" once at least one platform got the post
        if approval.bag is not None:
            approval.bag.status = "done"
            approval.bag.processed_at = datetime.now(timezone.utc)

    db.session.commit()

    return {
        "success": fb_result["success"] or ig_result["success"],
        "fb_status": log.fb_status,
        "ig_status": log.ig_status,
        "fb_post_id": log.fb_post_id,
        "ig_post_id": log.ig_post_id,
        "post_log_id": log.id,
        "error": None if (fb_result["success"] or ig_result["success"]) else "both platforms failed",
    }


# ---------------------------------------------------------------------------
# Public: per-platform posters
# ---------------------------------------------------------------------------

def post_to_facebook_only(approval_id: int, tenant_id: str = "default") -> dict:
    """Retry just the Facebook half of an approval (IG already succeeded).

    Used when post_to_both posted to IG but FB failed (e.g. wrong token type).
    Updates the existing PostLog row's fb_* fields instead of creating a duplicate
    log. Does NOT call post_to_instagram so we don't double-publish there.

    Returns: {success, fb_status, fb_post_id, error}
    """
    from ..models import PendingApproval, PostLog
    from ...extensions import db

    approval = db.session.get(PendingApproval, approval_id)
    if approval is None:
        return _err("Approval not found")
    if not approval.generated_image_url:
        return _err("Approval has no generated_image_url")

    caption = approval.fb_caption or generate_caption(approval, platform="fb")
    fb_result = post_to_facebook(approval.generated_image_url, caption, tenant_id)

    log = approval.post_log
    if log is None:
        log = PostLog(tenant_id=tenant_id, approval_id=approval_id, caption=caption)
        db.session.add(log)
    log.fb_status = "success" if fb_result["success"] else "failed"
    log.fb_post_id = fb_result.get("post_id")
    log.fb_error = fb_result.get("error")

    if fb_result["success"]:
        approval.status = "posted"
        approval.responded_at = datetime.now(timezone.utc)
        if approval.bag is not None:
            approval.bag.status = "done"
            approval.bag.processed_at = datetime.now(timezone.utc)

    db.session.commit()
    return {
        "success": fb_result["success"],
        "fb_status": log.fb_status,
        "fb_post_id": fb_result.get("post_id"),
        "error": fb_result.get("error"),
    }


def post_to_facebook(image_url: str, caption: str, tenant_id: str = "default") -> dict:
    """POST /{page_id}/photos — publishes a photo to the Facebook Page.

    Returns: {success, post_id, error}
    """
    token = os.environ.get("FB_PAGE_TOKEN")
    page_id = os.environ.get("FB_PAGE_ID")
    if not token or not page_id:
        return _platform_err("FB_PAGE_TOKEN or FB_PAGE_ID not set")

    url = f"{META_GRAPH_BASE}/{page_id}/photos"
    data = {
        "url": image_url,
        "caption": caption,
        "access_token": token,
    }
    response = _post_with_retry(url, data=data, platform="FB")
    if response is None:
        return _platform_err("FB API call failed after retries")

    if response.status_code != 200:
        return _handle_meta_error(response, platform="FB")

    body = response.json()
    post_id = body.get("post_id") or body.get("id")
    if not post_id:
        return _platform_err(f"FB response missing post_id: {body}")

    _log_rate_limits(response, "FB")
    logger.info("Posted to Facebook: %s", post_id)
    return {"success": True, "post_id": post_id, "error": None}


def post_to_instagram(image_url: str, caption: str, tenant_id: str = "default") -> dict:
    """Three-step IG Business publishing.

    1. POST /{ig_id}/media         — create container
    2. Poll status_code = FINISHED — up to 30s
    3. POST /{ig_id}/media_publish — publish

    Returns: {success, post_id, error}
    """
    token = os.environ.get("FB_PAGE_TOKEN")
    ig_id = os.environ.get("IG_BUSINESS_ACCOUNT_ID")
    if not token or not ig_id:
        return _platform_err("FB_PAGE_TOKEN or IG_BUSINESS_ACCOUNT_ID not set")

    # --- Step 1: create container ---
    container_url = f"{META_GRAPH_BASE}/{ig_id}/media"
    response = _post_with_retry(
        container_url,
        data={"image_url": image_url, "caption": caption, "access_token": token},
        platform="IG",
    )
    if response is None:
        return _platform_err("IG container creation failed after retries")
    if response.status_code != 200:
        return _handle_meta_error(response, platform="IG")

    container_id = response.json().get("id")
    if not container_id:
        return _platform_err(f"IG container response missing id: {response.text[:200]}")

    # --- Step 2: poll until FINISHED ---
    status = _poll_ig_container(container_id, token)
    if status != "FINISHED":
        return _platform_err(f"IG container did not finish processing (status={status})")

    # --- Step 3: publish ---
    publish_url = f"{META_GRAPH_BASE}/{ig_id}/media_publish"
    response = _post_with_retry(
        publish_url,
        data={"creation_id": container_id, "access_token": token},
        platform="IG",
    )
    if response is None:
        return _platform_err("IG publish failed after retries")
    if response.status_code != 200:
        return _handle_meta_error(response, platform="IG")

    post_id = response.json().get("id")
    if not post_id:
        return _platform_err(f"IG publish response missing id: {response.text[:200]}")

    _log_rate_limits(response, "IG")
    logger.info("Posted to Instagram: %s", post_id)
    return {"success": True, "post_id": post_id, "error": None}


# ---------------------------------------------------------------------------
# Public: caption generator
# ---------------------------------------------------------------------------

def generate_caption(approval, platform: str = "fb") -> str:
    """Build a caption for FB or IG. Override via Setting('fb_caption_template').

    Supported variables: {bag_name}, {bag_id}, {category}, {price}
    """
    from ..models import Setting

    if platform not in ("fb", "ig"):
        raise ValueError(f"platform must be 'fb' or 'ig', got {platform!r}")

    key = f"{platform}_caption_template"
    default = DEFAULT_FB_TEMPLATE if platform == "fb" else DEFAULT_IG_TEMPLATE
    template = Setting.get(key, default=default) or default

    bag = approval.bag
    bag_name = bag.bag_name if bag else "Bag"
    variables = {
        "bag_name": bag_name,
        "bag_id": bag.id if bag else "",
        "category": "",  # reserved for future
        "price": "",     # reserved for future
        "emoji": pick_emoji_for_bag(bag_name),
    }

    try:
        return template.format(**variables)
    except (KeyError, IndexError) as exc:
        logger.warning("Caption template error: %s — falling back to default", exc)
        return default.format(**variables)


# ---------------------------------------------------------------------------
# Public: token validator (used by scripts/check_meta_token.py)
# ---------------------------------------------------------------------------

def check_token() -> dict:
    """Verify FB_PAGE_TOKEN is valid. Returns details on expiry."""
    token = os.environ.get("FB_PAGE_TOKEN")
    if not token:
        return {"valid": False, "error": "FB_PAGE_TOKEN not set"}

    # 1. Basic identity check
    try:
        me = requests.get(
            f"{META_GRAPH_BASE}/me",
            params={"access_token": token, "fields": "id,name"},
            timeout=HTTP_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        return {"valid": False, "error": f"Network error: {exc}"}

    if me.status_code != 200:
        return {"valid": False, "error": f"HTTP {me.status_code}: {me.text[:200]}"}

    name = me.json().get("name", "?")

    # 2. Debug token for expiry info
    try:
        debug = requests.get(
            f"{META_GRAPH_BASE}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=HTTP_TIMEOUT_SEC,
        )
        body = debug.json().get("data", {})
        expires_at = body.get("expires_at", 0)  # 0 means never expires
        data_access_expires_at = body.get("data_access_expires_at", 0)
    except Exception:
        expires_at = None
        data_access_expires_at = None

    return {
        "valid": True,
        "name": name,
        "expires_at": expires_at,
        "expires_in_days": (
            "never" if expires_at == 0
            else max(0, (expires_at - int(time.time())) // 86400) if expires_at else "unknown"
        ),
        "data_access_expires_at": data_access_expires_at,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _post_with_retry(
    url: str, data: dict, platform: str, retries: int = MAX_RETRIES,
) -> Optional[requests.Response]:
    """POST with exponential backoff on 5xx + network errors. 4xx fails fast."""
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SEC)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            logger.warning(
                "%s POST network error (attempt %d/%d): %s — retry in %ds",
                platform, attempt, retries, exc, wait,
            )
            if attempt < retries:
                time.sleep(wait)
            continue

        if response.status_code < 500:
            return response  # let caller inspect 2xx and 4xx

        wait = 2 ** attempt
        logger.warning(
            "%s POST %d (attempt %d/%d) — retry in %ds: %s",
            platform, response.status_code, attempt, retries, wait, response.text[:200],
        )
        if attempt < retries:
            time.sleep(wait)

    return None


def _poll_ig_container(container_id: str, token: str) -> str:
    """Poll container status until FINISHED, ERROR, EXPIRED, or timeout."""
    url = f"{META_GRAPH_BASE}/{container_id}"
    deadline = time.monotonic() + IG_CONTAINER_POLL_MAX_SEC

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                url,
                params={"fields": "status_code", "access_token": token},
                timeout=HTTP_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            logger.warning("IG container poll network error: %s", exc)
            time.sleep(IG_CONTAINER_POLL_INTERVAL_SEC)
            continue

        if response.status_code != 200:
            logger.error("IG container poll HTTP %d: %s",
                         response.status_code, response.text[:200])
            return "ERROR"

        status = response.json().get("status_code", "IN_PROGRESS")
        if status in ("FINISHED", "ERROR", "EXPIRED"):
            return status
        time.sleep(IG_CONTAINER_POLL_INTERVAL_SEC)

    return "TIMEOUT"


def _handle_meta_error(response: requests.Response, platform: str) -> dict:
    """Parse a Meta error response and decide whether to alert the admin."""
    try:
        body = response.json()
        err = body.get("error", {})
        code = err.get("code")
        msg = err.get("message", response.text[:200])
    except Exception:
        code = response.status_code
        msg = response.text[:200]

    full = f"{platform} HTTP {response.status_code} (code={code}): {msg}"
    logger.error(full)

    # 401 / 190 = OAuth / token issues → Telegram alert
    if response.status_code == 401 or code in (190, 102):
        _notify_admin(f"⚠️ Meta {platform} token expired or revoked.\n{msg}\n"
                      f"Regenerate at developers.facebook.com and update FB_PAGE_TOKEN.")

    return _platform_err(full)


def _log_rate_limits(response: requests.Response, platform: str) -> None:
    """If Meta returned usage headers, log a warning when usage > 80%."""
    header = response.headers.get("X-Business-Use-Case-Usage")
    if not header:
        return
    if "100" in header or "9" + "0" in header:  # crude high-usage check
        logger.warning("%s rate-limit usage header: %s", platform, header)


def _notify_admin(message: str) -> None:
    """Send a one-off alert message to the admin via Telegram (best-effort)."""
    try:
        from . import telegram_bot  # local import — avoid cycle
        loop = telegram_bot._bot_loop
        app = telegram_bot._application
        chat_id = telegram_bot._TELEGRAM_CHAT_ID
        if loop is None or app is None or not chat_id:
            return
        import asyncio
        asyncio.run_coroutine_threadsafe(
            app.bot.send_message(chat_id=chat_id, text=message), loop,
        )
    except Exception:
        logger.exception("Failed to send Telegram alert")


def _platform_err(message: str) -> dict:
    return {"success": False, "post_id": None, "error": message}


def _err(message: str) -> dict:
    logger.error("social_poster error: %s", message)
    return {
        "success": False,
        "fb_status": "skipped",
        "ig_status": "skipped",
        "fb_post_id": None,
        "ig_post_id": None,
        "post_log_id": None,
        "error": message,
    }
