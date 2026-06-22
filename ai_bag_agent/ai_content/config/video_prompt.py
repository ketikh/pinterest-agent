"""Image-to-video motion prompt builder for the Seedance model.

Called after a necklace photo is approved ("Approve & Generate Video") or when
a video is regenerated. Picks ONE style from the variation bank (never the same
style twice in a row) and builds a short, subtle-motion prompt.

Public API:
    build_video_prompt(previous_style=None, worn=True, style=None) -> dict
        returns {"style": <key>, "prompt": <one-line text>}

The caller sends `prompt` to Seedance and stores `style` to pass back as
`previous_style` next time.
"""

from __future__ import annotations

import random
from typing import Optional

# --- Variation bank: one opener per style (camera move + light + mood) --------
VIDEO_STYLES = {
    "A": "Slow cinematic push-in, warm golden-hour light, intimate premium mood",
    "B": "Gentle left-to-right parallax, clean bright studio light, crisp editorial mood",
    "C": "Soft camera pull-back reveal, diffused daylight, airy elegant mood",
    "D": "Subtle tilt-up along the necklace, cool refined light, luxury jewelry mood",
    "E": "Near-static frame with breathing light shimmer, shallow depth of field, dreamy bokeh",
    "F": "Slow drift with a soft focus rack, warm sunlit highlights, romantic mood",
}

# Light only — don't enumerate jewelry parts (listing metal/stones/chains made
# Seedance draw MORE of them).
_NECKLACE_LIGHT = "the necklace catches soft light with a gentle shimmer"
# Keep the product identical — Seedance kept inventing chains/threads/ribbons.
_NO_EXTRAS = (
    "keep the necklace exactly as in the source; add or change nothing — "
    "no chains, beads, threads, ribbons, or tails"
)
# Worn shot → only micro-motion on the person. Flat-lay → animate light only.
# Eyes MUST stay open (Seedance tended to leave them shut → unnatural).
_WORN_MOTION = (
    "model relaxed and natural, eyes open and never closed, subtle micro-motion: "
    "soft breeze in hair, faint smile"
)
_FLATLAY_MOTION = "animate only light, soft shadows, and the camera move"

# Mandatory closing clause (spec rule 6).
VIDEO_SUFFIX = (
    "photorealistic, soft natural lighting, keep necklace and hands stable, "
    "no distortion, no morphing."
)


def build_video_prompt(
    previous_style: Optional[str] = None,
    worn: bool = True,
    style: Optional[str] = None,
) -> dict:
    """Build one Seedance motion prompt.

    Args:
        previous_style: style key used last time; the new pick avoids it.
        worn: True if a person wears the necklace, False for a flat-lay.
        style: force a specific style key (skips random pick) — for tests/replay.

    Returns:
        {"style": <key in VIDEO_STYLES>, "prompt": <one-line plain-English text>}
    """
    key = style if style in VIDEO_STYLES else _pick_style(previous_style)
    opener = VIDEO_STYLES[key]
    motion = _WORN_MOTION if worn else _FLATLAY_MOTION
    # _NO_EXTRAS stops Seedance inventing dangling threads/ribbons; the loop
    # clause asks for matching first/last frames (GIF / Reels / Stories).
    prompt = (
        f"{opener}; {_NECKLACE_LIGHT}; {motion}; {_NO_EXTRAS}; "
        f"seamless loop where the first and last frame match; {VIDEO_SUFFIX}"
    )
    return {"style": key, "prompt": prompt}


def _pick_style(previous_style: Optional[str], styles: dict = VIDEO_STYLES) -> str:
    """Pick a random key from `styles`, never the one used last time."""
    choices = [k for k in styles if k != previous_style]
    if not choices:  # previous_style was invalid/None-proof — use full bank
        choices = list(styles)
    return random.choice(choices)


# ---------------------------------------------------------------------------
# Bags / sleeves (TISSU) — separate prompt; protects fabric pattern + label
# ---------------------------------------------------------------------------

# Dynamic-but-logo-safe camera bank: each pairs a cinematic move with a tasteful
# ambient effect. NO push-in (it zoomed onto the mis-rendered TISSU label).
_BAG_STYLES = {
    "p": "slow cinematic orbit around the bag, soft light sweeping over the fabric, premium mood",
    "b": "gentle parallax with soft bokeh drifting in the background, clean daylight, editorial mood",
    "d": "smooth crane rise, a light breeze stirring the surroundings, warm lifestyle mood",
    "s": "elegant slow arc with a gentle rack focus and drifting light, dreamy mood",
}
# Guardrails so the richer motion still protects the product + logo.
_BAG_MOTION = (
    "bag stays stable and undistorted, no flicker; no zoom onto the logo; the "
    "logo stays small and sharp"
)
BAG_VIDEO_SUFFIX = (
    "photorealistic, soft natural lighting, keep bag shape, fabric pattern and "
    "TISSU label stable, no distortion, no morphing, no warping text."
)


def build_bag_video_prompt(
    previous_style: Optional[str] = None, style: Optional[str] = None,
) -> dict:
    """Bag/sleeve motion prompt. Keeps the fabric pattern + TISSU label stable,
    avoids zooming on the logo, and uses steady (non-flickering) light. Returns
    {"style": <key>, "prompt": <one-line text>}.
    """
    key = style if style in _BAG_STYLES else _pick_style(previous_style, _BAG_STYLES)
    prompt = f"{_BAG_STYLES[key]}; {_BAG_MOTION}; {BAG_VIDEO_SUFFIX}"
    return {"style": key, "prompt": prompt}


def build_video_prompt_for(
    product_type: str, previous_style: Optional[str] = None,
    style: Optional[str] = None,
) -> dict:
    """Route to the right builder by product type (necklace vs bag)."""
    if product_type == "bag":
        return build_bag_video_prompt(previous_style=previous_style, style=style)
    return build_video_prompt(previous_style=previous_style, worn=True, style=style)
