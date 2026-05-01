#!/usr/bin/env python3
"""
Stage 1 manual test — kie.ai Nano Banana Pro generator.

Usage:
    1. Copy your bag photo to:  storage/bags/sample.jpg
    2. Set environment:         source venv/bin/activate
    3. Run:                     python scripts/test_ai_generator.py

Notes:
    - The bag image must be accessible as a PUBLIC URL.
      Option A: Paste a Cloudinary URL (after Stage 2)
      Option B: Upload sample.jpg to any image host and paste the URL below.
    - Reference URL can be any Pinterest pin image URL.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Make sure the project root is on the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# CONFIG — change these two URLs before running
# ---------------------------------------------------------------------------

# Your bag photo as a public URL (Cloudinary, imgbb, or any public host)
# After Stage 2 (Cloudinary), replace this with the Cloudinary URL of your bag photo.
BAG_IMAGE_URL = "https://res.cloudinary.com/dw2yuqjrr/image/upload/v1777654735/tissu/uploads/extra_TP11_20260501165855.jpg"  # ← replace me

# Pinterest reference pin image URL (right-click any Pinterest image → Copy image address)
REFERENCE_URL = "https://i.pinimg.com/736x/92/23/02/922302fdfeff7c39c06d1d411699a017.jpg"  # ← replace me

# Optional extra instructions for this specific bag
CUSTOM_PROMPT = "Corporate style. Warm studio lighting."

TENANT_ID = "default"

# ---------------------------------------------------------------------------


def main() -> None:
    api_key = os.environ.get("KIE_AI_API_KEY") or os.environ.get("KIEAI_API_KEY")
    if not api_key:
        print("ERROR: KIE_AI_API_KEY not found in environment or .env file")
        sys.exit(1)

    print("=" * 60)
    print("kie.ai Nano Banana Pro — Stage 1 Test")
    print("=" * 60)
    print(f"Bag URL:       {BAG_IMAGE_URL[:60]}...")
    print(f"Reference URL: {REFERENCE_URL[:60]}...")
    print(f"Model:         {os.environ.get('KIE_AI_MODEL', 'nano-banana-pro')}")
    print()

    if "replace me" in BAG_IMAGE_URL or "replace me" in REFERENCE_URL:
        print("⚠️  Please update BAG_IMAGE_URL and REFERENCE_URL at the top of this script!")
        print("   Paste a real public URL for your bag photo and a Pinterest reference image.")
        sys.exit(1)

    from ai_bag_agent.ai_content.services.ai_generator import generate_image

    print("Generating image… (this takes 20-40 seconds)")
    t0 = time.monotonic()
    result = generate_image(
        bag_image_path=BAG_IMAGE_URL,
        reference_image_url=REFERENCE_URL,
        custom_prompt=CUSTOM_PROMPT,
        tenant_id=TENANT_ID,
    )
    elapsed = time.monotonic() - t0

    print()
    print("=" * 60)
    if result["success"]:
        print("✅ SUCCESS!")
        print(f"   Generated URL: {result['generated_url']}")
        print(f"   Local backup:  {result['local_path']}")
        print(f"   Model:         {result['model_used']}")
        print(f"   Time:          {result['generation_time_sec']:.1f}s")
        print()
        print("Open the generated image:")
        if result["local_path"]:
            local = result["local_path"]
            print(f"   open '{local}'  (macOS)")
    else:
        print("❌ FAILED")
        print(f"   Error: {result['error']}")
        print()
        print("Troubleshooting:")
        print("  • Check KIE_AI_API_KEY in .env is correct")
        print("  • Make sure BAG_IMAGE_URL is publicly accessible")
        print("  • Check kie.ai service status at https://kie.ai")
    print("=" * 60)


if __name__ == "__main__":
    main()
