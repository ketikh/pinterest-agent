#!/usr/bin/env python3
"""Stage 3 manual test — Pinterest Client."""

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

from ai_bag_agent.ai_content.services.pinterest_client import get_random_reference_pin


def main() -> None:
    board_id = os.environ.get("PINTEREST_BOARD_ID")
    token = os.environ.get("PINTEREST_ACCESS_TOKEN")

    print("=" * 60)
    print("Pinterest Client — Stage 3 Test")
    print("=" * 60)
    print(f"Board ID: {board_id}")
    print(f"Token:    {token[:20]}..." if token else "Token:    NOT SET")
    print()

    if not board_id or not token:
        print("ERROR: Set PINTEREST_BOARD_ID and PINTEREST_ACCESS_TOKEN in .env")
        sys.exit(1)

    print("Fetching random reference pin...")
    # exclude_recent=False for testing (no DB context available)
    pin = get_random_reference_pin(board_id, tenant_id="default", exclude_recent=False)

    print("=" * 60)
    if pin:
        print("✅ SUCCESS!")
        print(f"   Pin ID:     {pin.pin_id}")
        print(f"   Image URL:  {pin.image_url}")
        print(f"   Title:      {pin.title[:60] if pin.title else '(no title)'}")
        print(f"   Pin URL:    {pin.pin_url}")
        print()
        print("Open reference image:")
        print(f"   {pin.image_url}")
    else:
        print("❌ FAILED — no pin returned")
        print()
        print("Troubleshooting:")
        print("  • Check PINTEREST_ACCESS_TOKEN is fresh (24h expiry)")
        print("  • Check PINTEREST_BOARD_ID is correct")
        print("  • Run scripts/pinterest_auth.py to get a fresh token")
    print("=" * 60)


if __name__ == "__main__":
    main()
