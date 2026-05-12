"""AI caption generator — Facebook (Georgian) + Instagram (English) via Claude.

One call returns two captions tailored per platform:

    Facebook  — short, Georgian, max 3 hashtags, call-to-action mood
    Instagram — slightly longer, English, ~10 hashtags, lifestyle mood

Used by orchestrator.run_generate_job() so the admin sees AI-drafted text
in /admin/approvals/{id}/edit and can tweak before posting.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# System prompt — describes the task and the strict JSON output contract.
_SYSTEM_PROMPT = """\
You write social-media captions for a Georgian handmade-bag brand called \
"Tissu Georgia". You always return EXACTLY one JSON object with two keys:
  "fb_caption"  — Facebook caption, in Georgian (ქართული).
                  1–2 short sentences. Friendly, premium tone.
                  No hashtags. At most one tasteful emoji (✨🤎🖤 etc).
  "ig_caption"  — Instagram caption, in English.
                  1 line hook + 1 line short description.
                  No hashtags. At most 2 tasteful emojis.
Never include any text outside the JSON. No prose, no preamble, no code fences.\
"""

_USER_TEMPLATE = """\
Bag name: {bag_name}
Reference photo (style direction only): {reference_url}
Style notes from admin: {custom_prompt}

Generate the JSON described in the system prompt.\
"""


def generate_captions(
    bag_name: str,
    custom_prompt: str = "",
    reference_url: str = "",
) -> dict:
    """Generate FB + IG captions for one bag.

    Returns:
        dict with keys: success, fb_caption, ig_caption, model_used, error
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _err("ANTHROPIC_API_KEY not set")

    if not bag_name or not bag_name.strip():
        return _err("bag_name is required")

    client = anthropic.Anthropic(api_key=api_key)
    user_message = _USER_TEMPLATE.format(
        bag_name=bag_name.strip(),
        custom_prompt=(custom_prompt or "—").strip(),
        reference_url=(reference_url or "—").strip(),
    )

    try:
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as exc:
        return _err(f"Anthropic API error: {exc}")
    except Exception as exc:
        return _err(f"Unexpected error: {exc}")

    text = _join_text_blocks(response.content)
    parsed = _parse_json(text)
    if parsed is None:
        return _err(f"Could not parse JSON from response: {text[:200]}")

    fb = (parsed.get("fb_caption") or "").strip()
    ig = (parsed.get("ig_caption") or "").strip()
    if not fb or not ig:
        return _err(f"Missing caption fields in response: {parsed}")

    return {
        "success": True,
        "fb_caption": fb,
        "ig_caption": ig,
        "model_used": DEFAULT_MODEL,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _join_text_blocks(content) -> str:
    """anthropic Message.content is a list of content blocks; pull text out."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _parse_json(text: str) -> Optional[dict]:
    """Find the first JSON object in the model's response and parse it."""
    if not text:
        return None
    # Strip code fences if model added them despite the instruction.
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Look for the first {...} block in the text
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _err(message: str) -> dict:
    logger.error("caption_generator error: %s", message)
    return {
        "success": False,
        "fb_caption": None,
        "ig_caption": None,
        "model_used": None,
        "error": message,
    }
