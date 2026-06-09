"""kie.ai Nano Banana Pro image generation service.

Endpoint docs: https://docs.kie.ai/market/google/pro-image-to-image
Flow:
  1. POST /api/v1/jobs/createTask  → taskId
  2. Poll GET /api/v1/jobs/recordInfo?taskId=...  → state: success | fail
  3. Parse resultJson → resultUrls[0]
  4. Download generated image to storage/generated/ as local backup
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from ..config.prompt_template import build_prompt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KIE_API_BASE = "https://api.kie.ai/api/v1"
CREATE_TASK_URL = f"{KIE_API_BASE}/jobs/createTask"
POLL_URL = f"{KIE_API_BASE}/jobs/recordInfo"

RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
POLL_INTERVAL_SEC = 5
# Nano Banana Pro typically finishes in 20-60s but can spike to 3-5 min during
# peak hours. 5 min is a generous ceiling that still bounds a stuck request.
POLL_TIMEOUT_SEC = int(os.environ.get("KIE_AI_POLL_TIMEOUT_SEC", "300"))


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    success: bool
    generated_url: Optional[str] = None
    local_path: Optional[str] = None
    model_used: str = "nano-banana-pro"
    generation_time_sec: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "generated_url": self.generated_url,
            "local_path": self.local_path,
            "model_used": self.model_used,
            "generation_time_sec": round(self.generation_time_sec, 2),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_image(
    bag_image_path: str,
    reference_image_url: str,
    custom_prompt: str = "",
    tenant_id: str = "default",
    include_bag_input: bool = True,
    bag_image_open_url: Optional[str] = None,
) -> dict:
    """Generate a promotional bag photo using kie.ai Nano Banana Pro.

    Args:
        bag_image_path: Public URL of the bag photo (primary image).
                        Local file paths require Cloudinary (Stage 2).
        reference_image_url: Public URL of the Pinterest reference photo.
        custom_prompt: Optional per-bag prompt additions.
        tenant_id: Tenant identifier for storage organisation.
        bag_image_open_url: Optional URL of the SAME bag photographed open —
                            used purely as a reference so kie.ai understands
                            interior shape/proportions. The closed bag remains
                            the primary subject.

    Returns:
        dict with keys: success, generated_url, local_path,
                        model_used, generation_time_sec, error
    """
    api_key = os.environ.get("KIE_AI_API_KEY") or os.environ.get("KIEAI_API_KEY")
    if not api_key:
        return GenerationResult(
            success=False, error="KIE_AI_API_KEY not set in environment"
        ).to_dict()

    model = os.environ.get("KIE_AI_MODEL", "nano-banana-pro")
    max_retries = int(os.environ.get("KIE_AI_MAX_RETRIES", "3"))

    bag_url = _resolve_image_url(bag_image_path)
    if bag_url is None:
        return GenerationResult(
            success=False,
            error=(
                f"Cannot use local path '{bag_image_path}' without Cloudinary. "
                "Upload the image to Cloudinary first (Stage 2), "
                "or provide a public URL."
            ),
        ).to_dict()

    # Pad bag to 1:1 square so kie.ai (which always returns square output)
    # doesn't squash a portrait/landscape bag to fit. White padding fills
    # the empty space; AI replaces it with the styled background.
    bag_url = _pad_to_square_cloudinary(bag_url)
    reference_image_url = _pad_to_square_cloudinary(reference_image_url)

    bag_open_url: Optional[str] = None
    if bag_image_open_url:
        resolved_open = _resolve_image_url(bag_image_open_url)
        if resolved_open is not None:
            bag_open_url = _pad_to_square_cloudinary(resolved_open)
        else:
            logger.warning(
                "bag_image_open_url is not a public URL (%s) — ignoring",
                bag_image_open_url,
            )

    prompt = build_prompt(custom_prompt, has_open_bag=bool(bag_open_url))
    t_start = time.monotonic()

    # Step 1 — submit task (with retries for server overload)
    # include_bag_input=False is used by the scene-only composite pipeline:
    # kie.ai gets ONLY the reference photo + text prompt and generates an
    # empty scene; the bag is composited locally afterwards.
    task_id = _submit_task(
        api_key=api_key,
        model=model,
        bag_url=bag_url if include_bag_input else None,
        reference_url=reference_image_url,
        prompt=prompt,
        max_retries=max_retries,
        bag_open_url=bag_open_url,
    )
    if task_id is None:
        return GenerationResult(
            success=False,
            error="Failed to submit generation task after retries",
            generation_time_sec=time.monotonic() - t_start,
        ).to_dict()

    logger.info("kie.ai task submitted", extra={"task_id": task_id, "tenant_id": tenant_id})

    # Step 2 — poll for result
    generated_url, poll_error = _poll_for_result(api_key=api_key, task_id=task_id)
    elapsed = time.monotonic() - t_start

    if poll_error or not generated_url:
        logger.error(
            "kie.ai generation failed",
            extra={"task_id": task_id, "error": poll_error, "elapsed": elapsed},
        )
        return GenerationResult(
            success=False,
            error=poll_error or "No result URL returned",
            model_used=model,
            generation_time_sec=elapsed,
        ).to_dict()

    # Step 3 — download local backup
    local_path = _download_generated(
        url=generated_url,
        tenant_id=tenant_id,
    )

    logger.info(
        "kie.ai generation complete",
        extra={"task_id": task_id, "elapsed": elapsed, "local_path": local_path},
    )

    return GenerationResult(
        success=True,
        generated_url=generated_url,
        local_path=local_path,
        model_used=model,
        generation_time_sec=elapsed,
    ).to_dict()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pad_to_square_cloudinary(url: str) -> str:
    """Cloudinary URL transformation: pad to 1:1 square with white background.

    Keeps the bag's actual aspect ratio inside a 2048×2048 canvas so kie.ai
    receives a pre-squared image and doesn't have to squash or crop.
    Returns the URL unchanged when it's not a Cloudinary URL.
    """
    if not url or "res.cloudinary.com" not in url or "/upload/" not in url:
        return url
    return url.replace(
        "/upload/",
        "/upload/c_pad,b_white,ar_1:1,w_2048,h_2048/",
        1,
    )


def _resolve_image_url(path: str) -> Optional[str]:
    """Return URL if path is already a URL, else None (local paths unsupported here)."""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return None


def _build_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _submit_task(
    api_key: str,
    model: str,
    bag_url: str,
    reference_url: str,
    prompt: str,
    max_retries: int = 3,
    bag_open_url: Optional[str] = None,
) -> Optional[str]:
    """Submit a generation task. Returns taskId or None on failure.

    Note: image_input ORDER —
      [0] PRIMARY = the closed bag (the subject being sold)
      [1] REFERENCE = Pinterest scene/lighting guide
      [2] OPEN VIEW (optional) = the same bag, opened — interior reference only

    The prompt template addresses each slot by ordinal, so don't reorder.
    """
    if bag_url:
        image_input = [bag_url, reference_url]
        if bag_open_url:
            image_input.append(bag_open_url)
    else:
        image_input = [reference_url]
    payload = {
        "model": model,
        "input": {
            "prompt": prompt,
            "image_input": image_input,
            "aspect_ratio": "1:1",
            "resolution": "2K",
            "output_format": "png",
        },
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                CREATE_TASK_URL,
                headers=_build_headers(api_key),
                json=payload,
                timeout=30,
            )
        except requests.Timeout:
            logger.warning("kie.ai submit timeout (attempt %d/%d)", attempt, max_retries)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            continue
        except requests.RequestException as exc:
            logger.warning(
                "kie.ai submit error (attempt %d/%d): %s", attempt, max_retries, exc
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            body = resp.json()
            if body.get("code") == 200:
                return body["data"]["taskId"]
            logger.warning("kie.ai non-200 code: %s", body.get("msg"))
            return None

        if resp.status_code in RETRIABLE_STATUS_CODES:
            wait = 2 ** attempt
            logger.warning(
                "kie.ai %d on submit (attempt %d/%d), retrying in %ds",
                resp.status_code, attempt, max_retries, wait,
            )
            time.sleep(wait)
            continue

        logger.error("kie.ai submit HTTP %d: %s", resp.status_code, resp.text[:200])
        return None

    logger.error("kie.ai submit failed after %d attempts", max_retries)
    return None


def _poll_for_result(
    api_key: str,
    task_id: str,
    poll_interval: int = POLL_INTERVAL_SEC,
    timeout: int = POLL_TIMEOUT_SEC,
) -> tuple[Optional[str], Optional[str]]:
    """Poll until task is complete. Returns (generated_url, error_message)."""
    start = time.monotonic()
    deadline = start + timeout
    headers = _build_headers(api_key)
    last_info_log = start

    while time.monotonic() < deadline:
        try:
            resp = requests.get(
                POLL_URL,
                headers=headers,
                params={"taskId": task_id},
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning("kie.ai poll error for %s: %s", task_id, exc)
            time.sleep(poll_interval)
            continue

        if resp.status_code != 200:
            logger.warning("kie.ai poll HTTP %d for %s", resp.status_code, task_id)
            time.sleep(poll_interval)
            continue

        body = resp.json()
        data = body.get("data", {})
        state = data.get("state", "")

        if state == "success":
            result_json_str = data.get("resultJson", "{}")
            try:
                result = json.loads(result_json_str)
                urls: list = result.get("resultUrls", [])
                if urls:
                    return urls[0], None
                return None, "resultUrls is empty"
            except json.JSONDecodeError as exc:
                return None, f"Failed to parse resultJson: {exc}"

        if state == "fail":
            fail_msg = data.get("failMsg", "unknown failure")
            return None, f"kie.ai task failed: {fail_msg}"

        # Still in progress (waiting / queuing / generating)
        now = time.monotonic()
        elapsed = int(now - start)
        if now - last_info_log >= 30:
            logger.info("kie.ai task %s state=%s, %ds elapsed / %ds budget",
                        task_id, state, elapsed, timeout)
            last_info_log = now
        else:
            logger.debug("kie.ai task %s state=%s, %ds elapsed", task_id, state, elapsed)
        time.sleep(poll_interval)

    return None, f"Timed out waiting for task {task_id} after {timeout}s"


def _download_generated(url: str, tenant_id: str) -> Optional[str]:
    """Download the kie.ai PNG, recompress to JPEG so it fits Cloudinary's
    10 MB free-tier upload limit and Telegram's 10 MB multipart cap.

    kie.ai's 2K PNG output runs 10–12 MB; uploading raw blows up at Cloudinary
    and the resulting URL is unfetchable by Telegram. JPEG at q=88 with a
    2048 px ceiling keeps detail while landing well under 2 MB.
    """
    storage_dir = Path("/tmp/pinterest-agent-data/generated") / tenant_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    dest = storage_dir / f"{tenant_id}_{timestamp}.jpg"

    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Could not download generated image: %s", exc)
        return None

    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(resp.content))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        max_side = 2048
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        img.save(dest, format="JPEG", quality=88, optimize=True, progressive=True)
        logger.info("Compressed generated image: %d B → %s (%d B)",
                    len(resp.content), dest.name, dest.stat().st_size)
        return str(dest)
    except Exception as exc:
        # Pillow failure → keep raw bytes so admin still has something to
        # work with, even if Cloudinary upload later rejects it.
        logger.warning("Pillow compress failed (%s) — saving raw bytes", exc)
        dest_raw = storage_dir / f"{tenant_id}_{timestamp}_raw.png"
        try:
            dest_raw.write_bytes(resp.content)
            return str(dest_raw)
        except Exception:
            return None
