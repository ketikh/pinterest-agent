"""Pixel-faithful bag preservation via background removal + composite.

Generative models (kie.ai Nano Banana) interpret the input bag and routinely
redraw it — different proportions, repositioned logo, added/removed straps.
That's intolerable for an e-commerce catalogue.

This module sidesteps the issue: we ask the AI to generate ONLY the scene
(no product), strip the original bag photo's background with rembg, and
composite the original bag pixels onto the AI scene with Pillow. Result:
the bag is byte-identical to the input; only the surroundings change.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def extract_bag_with_alpha(image_url: str) -> Optional[bytes]:
    """Download `image_url` and remove the background. Returns PNG bytes
    (transparent where the original background was)."""
    try:
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Bag photo download failed: %s", exc)
        return None

    try:
        from rembg import remove
    except ImportError:
        logger.error("rembg not installed — cannot extract bag")
        return None

    try:
        return remove(resp.content)
    except Exception as exc:
        logger.exception("Background removal failed for %s: %s",
                         image_url[:80], exc)
        return None


def composite_bag_on_scene(
    bag_png_bytes: bytes,
    scene_image_url: str,
    canvas_size: int = 2048,
    bag_scale: float = 0.72,
    vertical_offset_frac: float = 0.04,
) -> Optional[bytes]:
    """Place the bag (with alpha) centred on an AI-generated scene.

    Returns JPEG bytes ready to upload to Cloudinary. Adds a soft drop
    shadow under the bag so the result doesn't look obviously pasted on.
    """
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        logger.error("Pillow not available — cannot composite")
        return None

    try:
        r = requests.get(scene_image_url, timeout=60)
        r.raise_for_status()
        scene = Image.open(BytesIO(r.content)).convert("RGBA")
        bag = Image.open(BytesIO(bag_png_bytes)).convert("RGBA")
    except Exception as exc:
        logger.error("Composite input load failed: %s", exc)
        return None

    # Normalise scene to a square canvas at the desired resolution.
    if scene.size != (canvas_size, canvas_size):
        scene = scene.resize((canvas_size, canvas_size), Image.LANCZOS)

    # Auto-orient the bag to fit the canvas — rotate 90° if it's wider than
    # tall AND the scene's empty area is taller than wide (typical case). The
    # bag's actual shape, colour and details stay identical; only its
    # placement orientation rotates.
    bag = _auto_orient_for_canvas(bag, canvas_size)

    # Scale the bag to bag_scale of the canvas while preserving aspect.
    max_dim = int(canvas_size * bag_scale)
    bag.thumbnail((max_dim, max_dim), Image.LANCZOS)

    x = (scene.width - bag.width) // 2
    y = (scene.height - bag.height) // 2 + int(scene.height * vertical_offset_frac)

    # Drop shadow — soft, offset down-right.
    shadow_alpha_cap = 80
    try:
        alpha = bag.split()[3].point(lambda p: min(p, shadow_alpha_cap))
        shadow_solid = Image.new("RGBA", bag.size, (0, 0, 0, 0))
        shadow_solid.putalpha(alpha)
        shadow_layer = Image.new("RGBA", scene.size, (0, 0, 0, 0))
        shadow_layer.paste(shadow_solid, (x + 18, y + 36), shadow_solid)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(28))
        scene = Image.alpha_composite(scene, shadow_layer)
    except Exception as exc:
        logger.debug("Shadow step skipped: %s", exc)

    bag_layer = Image.new("RGBA", scene.size, (0, 0, 0, 0))
    bag_layer.paste(bag, (x, y), bag)
    scene = Image.alpha_composite(scene, bag_layer)

    out = BytesIO()
    scene.convert("RGB").save(
        out, format="JPEG", quality=88, optimize=True, progressive=True,
    )
    return out.getvalue()


def _auto_orient_for_canvas(bag, canvas_size: int):
    """Rotate the bag 90° if it's landscape on a square canvas — gives a
    bigger, more readable composite. Does NOT change the bag's shape or
    proportions, only its on-canvas orientation.

    Returns the (possibly rotated) bag image.
    """
    from PIL import Image
    w, h = bag.size
    # If bag is significantly wider than tall, rotate it upright so it can
    # be scaled larger without overflowing.
    if w > h * 1.15:
        return bag.rotate(90, expand=True, resample=Image.BICUBIC)
    return bag


def save_bytes_to_tmp(data: bytes, suffix: str = ".jpg") -> str:
    """Write `data` to a unique file under /tmp/ and return the path."""
    import os
    import time
    base = "/tmp/pinterest-agent-data/composites"
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"composite_{int(time.time() * 1000)}{suffix}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path
