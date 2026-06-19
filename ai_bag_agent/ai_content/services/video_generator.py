"""kie.ai Seedance image-to-video generation service.

Mirrors ai_generator.py (createTask → poll recordInfo) but for video: takes an
approved product image + a motion prompt (built by config.video_prompt) and
returns a video URL.

Model + params are env-configurable so the operator can tune cost/format
without a deploy. Defaults: Seedance 1.5 Pro, 9:16, 720p, 5s, no audio.

Public API:
    generate_video(image_url, prompt, tenant_id="default") -> dict
        {success, video_url, model_used, generation_time_sec, error}
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

from .ai_generator import (
    CREATE_TASK_URL,
    RETRIABLE_STATUS_CODES,
    _build_headers,
    _poll_for_result,
    _resolve_image_url,
)

logger = logging.getLogger(__name__)

# Seedance can take a few minutes — allow a generous poll ceiling.
VIDEO_POLL_TIMEOUT_SEC = int(os.environ.get("KIE_VIDEO_POLL_TIMEOUT_SEC", "600"))


@dataclass
class VideoResult:
    success: bool
    video_url: Optional[str] = None
    model_used: str = ""
    generation_time_sec: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "video_url": self.video_url,
            "model_used": self.model_used,
            "generation_time_sec": round(self.generation_time_sec, 2),
            "error": self.error,
        }


def _video_config() -> dict:
    """Read Seedance model + params from env (with social-ready defaults)."""
    audio_raw = os.environ.get("KIE_VIDEO_GENERATE_AUDIO", "false").strip().lower()
    return {
        "model": os.environ.get("KIE_VIDEO_MODEL", "bytedance/seedance-1.5-pro"),
        "aspect_ratio": os.environ.get("KIE_VIDEO_ASPECT_RATIO", "9:16"),
        "resolution": os.environ.get("KIE_VIDEO_RESOLUTION", "720p"),
        "duration": int(os.environ.get("KIE_VIDEO_DURATION", "5")),
        "generate_audio": audio_raw in ("1", "true", "yes", "on"),
    }


def generate_video(
    image_url: str, prompt: str, tenant_id: str = "default",
) -> dict:
    """Generate a short video from an approved product image + motion prompt.

    Args:
        image_url: public URL of the approved photo (the video's source frame).
        prompt: motion prompt from config.video_prompt.build_video_prompt().
        tenant_id: tenant identifier (logging only).

    Returns:
        dict: {success, video_url, model_used, generation_time_sec, error}
    """
    api_key = os.environ.get("KIE_AI_API_KEY") or os.environ.get("KIEAI_API_KEY")
    if not api_key:
        return VideoResult(success=False, error="KIE_AI_API_KEY not set").to_dict()

    src = _resolve_image_url(image_url)
    if src is None:
        return VideoResult(
            success=False,
            error=f"image_url must be a public URL, got '{image_url}'",
        ).to_dict()

    cfg = _video_config()
    max_retries = int(os.environ.get("KIE_AI_MAX_RETRIES", "3"))
    t_start = time.monotonic()

    task_id = _submit_video_task(api_key, src, prompt, cfg, max_retries)
    if task_id is None:
        return VideoResult(
            success=False,
            error="Failed to submit video task after retries",
            model_used=cfg["model"],
            generation_time_sec=time.monotonic() - t_start,
        ).to_dict()

    logger.info("Seedance task submitted",
                extra={"task_id": task_id, "tenant_id": tenant_id})

    video_url, poll_error = _poll_for_result(
        api_key=api_key, task_id=task_id, timeout=VIDEO_POLL_TIMEOUT_SEC,
    )
    elapsed = time.monotonic() - t_start

    if poll_error or not video_url:
        logger.error("Seedance generation failed",
                     extra={"task_id": task_id, "error": poll_error})
        return VideoResult(
            success=False,
            error=poll_error or "No video URL returned",
            model_used=cfg["model"],
            generation_time_sec=elapsed,
        ).to_dict()

    logger.info("Seedance generation complete",
                extra={"task_id": task_id, "elapsed": elapsed})
    return VideoResult(
        success=True,
        video_url=video_url,
        model_used=cfg["model"],
        generation_time_sec=elapsed,
    ).to_dict()


def _submit_video_task(
    api_key: str, image_url: str, prompt: str, cfg: dict, max_retries: int = 3,
) -> Optional[str]:
    """POST createTask for a Seedance video. Returns taskId or None."""
    payload = {
        "model": cfg["model"],
        "input": {
            "prompt": prompt,
            "image_input": [image_url],
            "aspect_ratio": cfg["aspect_ratio"],
            "resolution": cfg["resolution"],
            "duration": cfg["duration"],
            "generate_audio": cfg["generate_audio"],
        },
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                CREATE_TASK_URL, headers=_build_headers(api_key),
                json=payload, timeout=30,
            )
        except requests.RequestException as exc:
            logger.warning("Seedance submit error (attempt %d/%d): %s",
                           attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            body = resp.json()
            if body.get("code") == 200:
                return body["data"]["taskId"]
            logger.warning("Seedance non-200 code: %s", body.get("msg"))
            return None

        if resp.status_code in RETRIABLE_STATUS_CODES and attempt < max_retries:
            time.sleep(2 ** attempt)
            continue

        logger.error("Seedance submit HTTP %d: %s", resp.status_code, resp.text[:200])
        return None

    return None
