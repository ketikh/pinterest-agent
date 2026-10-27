"""Image-URL recovery for Pinterest pins the board listing returns bare.

Pins saved from other users ("repins") frequently come back from
``GET /v5/boards/{id}/pins`` with a ``media`` block that has no image URLs.
When that happens the reference picker falls back to, in order:

  1. ``GET /v5/pins/{pin_id}`` — the single-pin payload sometimes includes
     the media the listing omitted.
  2. The pin's public web page — its ``og:image`` meta tag always points at
     the 736px pinimg.com rendition and needs no authentication.

Also hosts the board-level diagnostics used by ``/health/db?pins=1``.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import requests

from . import pinterest_client as pc

logger = logging.getLogger(__name__)

PIN_PAGE_URL = "https://www.pinterest.com/pin/{pin_id}/"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_OG_IMAGE_PATTERNS = (
    re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', re.I),
    re.compile(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', re.I),
)


def resolve_pin_image_fallback(pin_id: str) -> tuple[Optional[str], Optional[str]]:
    """Find an image URL for a pin whose listing payload had none.

    Returns ``(url, source)`` where source is ``"pin-detail"`` or
    ``"pin-page"``, or ``(None, None)`` when both lookups fail.
    """
    detail = get_pin_detail(pin_id)
    if detail:
        try:
            return pc.get_best_image_url(detail), "pin-detail"
        except ValueError:
            logger.debug("pin detail for %s also has no image URL", pin_id)
    url = fetch_pin_page_image(pin_id)
    if url:
        return url, "pin-page"
    logger.warning("Could not recover an image URL for pin %s", pin_id)
    return None, None


def get_pin_detail(pin_id: str) -> Optional[dict]:
    """``GET /v5/pins/{pin_id}``. Returns the raw pin dict, or None."""
    token = pc._get_token()
    if not token:
        return None
    try:
        resp = requests.get(
            f"{pc.BASE_URL}/pins/{pin_id}", headers=pc._headers(token), timeout=15
        )
    except requests.RequestException as exc:
        logger.warning("pin detail request failed for %s: %s", pin_id, exc)
        return None
    if resp.status_code != 200:
        logger.info("pin detail HTTP %d for %s", resp.status_code, pin_id)
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def fetch_pin_page_image(pin_id: str) -> Optional[str]:
    """Read ``og:image`` from the public pin page. None on any failure."""
    try:
        resp = requests.get(
            PIN_PAGE_URL.format(pin_id=pin_id),
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/html"},
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.warning("pin page fetch failed for %s: %s", pin_id, exc)
        return None
    if resp.status_code != 200:
        logger.warning("pin page HTTP %d for %s", resp.status_code, pin_id)
        return None
    return parse_og_image(resp.text)


def parse_og_image(html: str) -> Optional[str]:
    """Extract the pinimg.com ``og:image`` URL from HTML (either attribute order)."""
    for pattern in _OG_IMAGE_PATTERNS:
        match = pattern.search(html or "")
        if match and "pinimg.com" in match.group(1):
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Diagnostics (used by /health/db?pins=1)
# ---------------------------------------------------------------------------

def image_key(url: Optional[str]) -> str:
    """Content hash of a pinimg URL (its file name without extension/size)."""
    if not url:
        return ""
    name = url.rsplit("/", 1)[-1]
    return name.split(".")[0]


def board_image_diagnostics(pins: list, test_fallback: bool = True) -> dict:
    """Summarise how many listed pins carry an image URL, with a small
    sample of media shapes and (optionally) a live fallback probe for the
    first bare pin. No secrets — ids and key names only."""
    usable = 0
    first_bare: Optional[dict] = None
    for pin in pins:
        try:
            pc.get_best_image_url(pin)
            usable += 1
        except ValueError:
            first_bare = first_bare or pin

    sample = []
    for pin in pins[:3]:
        media = pin.get("media") or {}
        sample.append({
            "id": pin.get("id"),
            "is_owner": pin.get("is_owner"),
            "has_parent": bool(pin.get("parent_pin_id")),
            "media_type": media.get("media_type"),
            "media_keys": sorted(media.keys()),
            "image_sizes": sorted((media.get("images") or {}).keys()),
        })

    # Which image-size keys each pin carries, e.g. {"1200x,150x150,400x300,600x": 40,
    # "150x150,400x300,600x": 13}. Small originals never get a 1200x rendition.
    size_sets: dict = {}
    for pin in pins:
        images = (pin.get("media") or {}).get("images") or {}
        key = ",".join(sorted(images.keys())) or "(none)"
        size_sets[key] = size_sets.get(key, 0) + 1

    # Several pins can carry the SAME image (re-saved duplicates). pinimg URLs
    # end in /<content-hash>.<ext>, so group pins by that hash.
    by_image: dict = {}
    for pin in pins:
        try:
            url = pc.get_best_image_url(pin)
        except ValueError:
            continue
        by_image.setdefault(image_key(url), []).append(pin.get("id"))

    out = {
        "usable_in_listing": usable, "bare": len(pins) - usable,
        "distinct_images": len(by_image),
        "duplicate_groups": [ids for ids in by_image.values() if len(ids) > 1],
        "image_size_sets": size_sets, "sample": sample,
    }
    if test_fallback and first_bare is not None:
        url, source = resolve_pin_image_fallback(first_bare["id"])
        out["fallback_test"] = {
            "pin_id": first_bare["id"], "resolved": bool(url), "via": source,
        }
    return out
