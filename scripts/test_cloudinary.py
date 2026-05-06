#!/usr/bin/env python3
"""Stage 2 manual test — Cloudinary uploader."""

from __future__ import annotations

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

from ai_bag_agent.ai_content.services.cloudinary_svc import upload_image


def main() -> None:
    # Find any generated image (project storage, or legacy path outside project)
    candidate_dirs = [
        project_root / "storage" / "generated" / "default",
        Path.home() / "storage" / "generated" / "default",
    ]
    images = []
    for d in candidate_dirs:
        if d.exists():
            images.extend(sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True))
    images = sorted(images, key=lambda p: p.stat().st_mtime, reverse=True)

    if not images:
        print("ERROR: No generated images found.")
        print("Run scripts/test_ai_generator.py first to generate an image.")
        sys.exit(1)

    test_image = images[0]
    print("=" * 60)
    print("Cloudinary Upload — Stage 2 Test")
    print("=" * 60)
    print(f"Uploading: {test_image.name}")
    print(f"Folder:    tissu-ai/tenants/default/generated/")
    print()

    result = upload_image(str(test_image), tenant_id="default", category="generated")

    print("=" * 60)
    if result["success"]:
        print("✅ SUCCESS!")
        print(f"   Public URL:  {result['public_url']}")
        print(f"   Public ID:   {result['public_id']}")
        print(f"   Size:        {result['size_bytes'] // 1024} KB")
        print(f"   Dimensions:  {result['width']}x{result['height']}")
        print()
        print("Open in browser:")
        print(f"   {result['public_url']}")
    else:
        print("❌ FAILED")
        print(f"   Error: {result['error']}")
        print()
        print("Troubleshooting:")
        print("  • Check CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET in .env")
        print("  • Check Cloudinary dashboard for account status")
    print("=" * 60)


if __name__ == "__main__":
    main()
