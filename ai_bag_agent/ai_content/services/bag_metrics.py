"""Measure the bag's real geometry from its catalogue photo.

The generator tends to "harmonise" the bag's proportions with the scene or
with the reference pin. Telling it the measured width:height ratio of the
actual bag gives it a concrete number to hit instead of a vague "keep the
proportions". Catalogue photos have a flat background, so the bag's
bounding box is simply the region that differs from the border colour.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_MAX_SIDE = 512          # downscale for speed; ratio is scale-invariant
_DIFF_THRESHOLD = 28     # 0-255 luminance difference from the background
_SQUARE_TOLERANCE = 0.05


def measure_bag_geometry(image_url: str, timeout: int = 20) -> Optional[dict]:
    """Return ``{"ratio", "orientation", "box_w", "box_h"}`` or None.

    ``ratio`` is bounding-box width / height (2 decimals). Never raises:
    any download or decode problem returns None and the prompt goes out
    without the measured block.
    """
    try:
        resp = requests.get(image_url, timeout=timeout)
        resp.raise_for_status()
        return geometry_from_bytes(resp.content)
    except Exception as exc:  # noqa: BLE001 — best-effort helper
        logger.info("bag geometry skipped for %s: %s", image_url, exc)
        return None


def geometry_from_bytes(data: bytes) -> Optional[dict]:
    """Bounding box of everything that is not background colour."""
    from PIL import Image, ImageChops

    img = Image.open(BytesIO(data)).convert("RGB")
    if max(img.size) > _MAX_SIDE:
        img.thumbnail((_MAX_SIDE, _MAX_SIDE))

    background = Image.new("RGB", img.size, _border_colour(img))
    diff = ImageChops.difference(img, background).convert("L")
    mask = diff.point(lambda v: 255 if v > _DIFF_THRESHOLD else 0)
    bbox = mask.getbbox()
    if not bbox:
        return None
    box_w, box_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if box_w < 8 or box_h < 8:
        return None
    ratio = round(box_w / box_h, 2)
    if ratio < 1 - _SQUARE_TOLERANCE:
        orientation = "portrait"
    elif ratio > 1 + _SQUARE_TOLERANCE:
        orientation = "landscape"
    else:
        orientation = "square"
    return {"ratio": ratio, "orientation": orientation, "box_w": box_w, "box_h": box_h}


def _border_colour(img) -> tuple:
    """Median colour of the image border (robust background estimate)."""
    w, h = img.size
    pixels = []
    for x in range(0, w, max(1, w // 64)):
        pixels.append(img.getpixel((x, 0)))
        pixels.append(img.getpixel((x, h - 1)))
    for y in range(0, h, max(1, h // 64)):
        pixels.append(img.getpixel((0, y)))
        pixels.append(img.getpixel((w - 1, y)))
    channels = zip(*pixels)
    return tuple(sorted(c)[len(c) // 2] for c in (list(ch) for ch in channels))


def describe_geometry(geometry: Optional[dict]) -> str:
    """Prompt text for the measured geometry; empty string when unknown."""
    if not geometry:
        return ""
    ratio = geometry["ratio"]
    if geometry["orientation"] == "portrait":
        detail = f"about {round((1 / ratio - 1) * 100)}% taller than it is wide"
    elif geometry["orientation"] == "landscape":
        detail = f"about {round((ratio - 1) * 100)}% wider than it is tall"
    else:
        detail = "essentially square"
    return (
        "MEASURED GEOMETRY OF THE PRIMARY BAG (ground truth, taken from the input photo):\n"
        f"- Bounding box width : height = {ratio:.2f} : 1.00 — {geometry['orientation']}, "
        f"{detail}.\n"
        "- The output bag's bounding box MUST have this same ratio (within 5%). Do NOT\n"
        "  widen, narrow, stretch or shorten it to fit the scene, the model's pose, or the\n"
        "  reference bag. Measure before you finish; if the ratio differs, redo it."
    )
