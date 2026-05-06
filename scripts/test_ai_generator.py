#!/usr/bin/env python3
"""Full pipeline test — Pinterest → kie.ai → Cloudinary.

Usage:
    source venv/bin/activate
    python scripts/test_ai_generator.py

Steps:
    1. Get random reference pin from Pinterest board
    2. Generate promotional photo with kie.ai (bag + reference)
    3. Upload generated photo to Cloudinary
    4. Print all URLs
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Bag photo — Cloudinary public URL of the bag to shoot
BAG_IMAGE_URL = "https://res.cloudinary.com/dw2yuqjrr/image/upload/v1777654735/tissu/uploads/extra_TP11_20260501165855.jpg"

# Pinterest board to pull reference from (auto via API, or override below)
BOARD_URL = os.environ.get(
    "PINTEREST_BOARD_URL",
    "https://www.pinterest.com/tissugeorgia/laptop-bags/",
)

# Optional manual reference override (leave empty to use Pinterest API)
REFERENCE_URL_OVERRIDE = ""

# Per-bag style notes (leave empty to use global prompt only)
CUSTOM_PROMPT = ""

TENANT_ID = "default"

# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 60)
    print("Full Pipeline: Pinterest → kie.ai → Cloudinary")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Get reference pin from Pinterest
    # ------------------------------------------------------------------
    if REFERENCE_URL_OVERRIDE:
        reference_url = REFERENCE_URL_OVERRIDE
        pin_id = "manual"
        print(f"Step 1: Using manual reference URL")
        print(f"        {reference_url[:70]}")
    else:
        print("Step 1: Getting random pin from Pinterest board…")
        from ai_bag_agent.ai_content.services.pinterest_client import get_random_pin
        pin_result = get_random_pin(board_url=BOARD_URL, tenant_id=TENANT_ID)
        if not pin_result["success"]:
            print(f"❌ Pinterest failed: {pin_result['error']}")
            print()
            print("Fix: regenerate PINTEREST_ACCESS_TOKEN at developers.pinterest.com")
            print("     or set REFERENCE_URL_OVERRIDE in this script")
            sys.exit(1)
        reference_url = pin_result["image_url"]
        pin_id = pin_result["pin_id"]
        print(f"✅ Pin: {pin_id}")
        print(f"   URL: {reference_url[:70]}")

    # ------------------------------------------------------------------
    # Step 2: Generate with kie.ai
    # ------------------------------------------------------------------
    print()
    print(f"Step 2: Generating with kie.ai (20-60s)…")
    print(f"        Bag:       {BAG_IMAGE_URL[:70]}")
    print(f"        Reference: {reference_url[:70]}")

    from ai_bag_agent.ai_content.services.ai_generator import generate_image
    t0 = time.monotonic()
    gen = generate_image(
        bag_image_path=BAG_IMAGE_URL,
        reference_image_url=reference_url,
        custom_prompt=CUSTOM_PROMPT,
        tenant_id=TENANT_ID,
    )
    elapsed = time.monotonic() - t0

    if not gen["success"]:
        print(f"❌ Generation failed: {gen['error']}")
        sys.exit(1)

    print(f"✅ Generated in {elapsed:.1f}s")
    print(f"   URL: {gen['generated_url']}")

    # ------------------------------------------------------------------
    # Step 3: Upload to Cloudinary
    # ------------------------------------------------------------------
    print()
    print("Step 3: Uploading to Cloudinary…")

    if not gen.get("local_path"):
        print("⚠️  No local backup to upload (download may have failed)")
        print(f"   Generated URL still accessible: {gen['generated_url']}")
    else:
        from ai_bag_agent.ai_content.services.cloudinary_svc import upload_generated_image
        upload = upload_generated_image(gen, tenant_id=TENANT_ID)

        if not upload["success"]:
            print(f"❌ Cloudinary upload failed: {upload['error']}")
        else:
            print(f"✅ Uploaded: {upload['public_url']}")
            print(f"   Size: {upload['size_bytes'] // 1024} KB  "
                  f"Dimensions: {upload['width']}x{upload['height']}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Bag:          {BAG_IMAGE_URL}")
    print(f"Reference:    {reference_url}")
    print(f"Generated:    {gen['generated_url']}")
    if gen.get("local_path"):
        print(f"Local backup: {gen['local_path']}")
    print()
    print("Open generated image:")
    print(f"  {gen['generated_url']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
