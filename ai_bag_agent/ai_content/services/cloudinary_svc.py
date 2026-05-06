"""Cloudinary image upload service.

Folder layout (never touches existing tissu/ folder):
  tissu-ai/
    tenants/
      {tenant_id}/
        generated/    ← AI-generated outputs
        bags/         ← source bag photos uploaded by admin
        references/   ← Pinterest pin cache (optional)

Public ID format:
  {tenant_id}_{category}_{YYYYMMDD}_{uuid8}
  e.g. default_generated_20260501_a1b2c3d4
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)

FOLDER_ROOT = os.environ.get("CLOUDINARY_FOLDER_ROOT", "tissu-ai")
RETRIABLE_HTTP_CODES = {500, 502, 503, 504}
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _configure() -> bool:
    """Apply Cloudinary config from env. Returns True if all credentials present."""
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        return False

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    return True


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def upload_image(
    local_path: str,
    tenant_id: str = "default",
    category: str = "generated",
    public_id_prefix: Optional[str] = None,
) -> dict:
    """Upload a local image file to Cloudinary.

    Args:
        local_path: Absolute path to the local image file.
        tenant_id: Tenant identifier (used in folder path and public_id).
        category: One of "generated", "bags", "references".
        public_id_prefix: Optional override for the public_id prefix.

    Returns:
        dict with keys: success, public_url, public_id, format,
                        size_bytes, width, height, error
    """
    if not _configure():
        return _error_result("CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET not set in environment")

    path = Path(local_path)
    if not path.exists():
        return _error_result(f"File not found: {local_path}")

    folder = f"{FOLDER_ROOT}/tenants/{tenant_id}/{category}"
    public_id = _make_public_id(tenant_id, category, public_id_prefix)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = cloudinary.uploader.upload(
                str(path),
                folder=folder,
                public_id=public_id,
                unique_filename=False,
                overwrite=False,
                resource_type="image",
            )
            logger.info(
                "Cloudinary upload success",
                extra={
                    "public_id": result.get("public_id"),
                    "tenant_id": tenant_id,
                    "category": category,
                    "bytes": result.get("bytes"),
                },
            )
            return {
                "success": True,
                "public_url": result["secure_url"],
                "public_id": result["public_id"],
                "format": result.get("format", ""),
                "size_bytes": result.get("bytes", 0),
                "width": result.get("width", 0),
                "height": result.get("height", 0),
                "error": None,
            }

        except cloudinary.exceptions.Error as exc:
            http_code = getattr(exc, "http_code", None)
            if http_code in RETRIABLE_HTTP_CODES and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    "Cloudinary %s error (attempt %d/%d), retrying in %ds",
                    http_code, attempt, MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue
            logger.error("Cloudinary upload failed: %s", exc)
            return _error_result(str(exc))

        except Exception as exc:
            logger.error("Cloudinary unexpected error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            return _error_result(str(exc))

    return _error_result(f"Upload failed after {MAX_RETRIES} attempts")


def upload_generated_image(generation_result: dict, tenant_id: str = "default") -> dict:
    """Convenience wrapper: upload the local_path from a generate_image() result.

    Args:
        generation_result: dict returned by ai_generator.generate_image()
        tenant_id: Tenant identifier.

    Returns:
        Same shape as upload_image().
    """
    if not generation_result.get("success"):
        return _error_result("Generation result is not successful — nothing to upload")

    local_path = generation_result.get("local_path")
    if not local_path:
        return _error_result("Generation result has no local_path — cannot upload")

    return upload_image(local_path, tenant_id=tenant_id, category="generated")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_public_id(tenant_id: str, category: str, prefix: Optional[str]) -> str:
    date_str = datetime.utcnow().strftime("%Y%m%d")
    uid = uuid.uuid4().hex[:8]
    base = prefix or f"{tenant_id}_{category}_{date_str}_{uid}"
    return base


def _error_result(message: str) -> dict:
    return {
        "success": False,
        "public_url": None,
        "public_id": None,
        "format": None,
        "size_bytes": 0,
        "width": 0,
        "height": 0,
        "error": message,
    }
