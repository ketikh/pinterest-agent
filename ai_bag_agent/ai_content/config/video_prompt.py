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

# Necklace must always catch light; product stays stable.
_NECKLACE_LIGHT = (
    "necklace catches light with soft shimmer and gentle highlights on metal, "
    "stones, and charms, pendants swaying faintly"
)
# Worn shot → only micro-motion on the person. Flat-lay → animate light only.
_WORN_MOTION = (
    "model still, only micro-motion: soft breeze in hair, faint smile, hands "
    "and face stable"
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
    # "seamless loop" so the clip can be looped (GIF / Reels / Stories).
    prompt = f"{opener}; {_NECKLACE_LIGHT}; {motion}; seamless loop; {VIDEO_SUFFIX}"
    return {"style": key, "prompt": prompt}


def _pick_style(previous_style: Optional[str]) -> str:
    """Pick a random style key, never the one used last time."""
    choices = [k for k in VIDEO_STYLES if k != previous_style]
    if not choices:  # previous_style was invalid/None-proof — use full bank
        choices = list(VIDEO_STYLES)
    return random.choice(choices)
