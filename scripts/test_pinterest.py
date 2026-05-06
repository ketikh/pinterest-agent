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

from ai_bag_agent.ai_content.services.pinterest_client import (
    get_user_boards,
    get_board_id_from_url,
    get_random_pin,
)

BOARD_URL = os.environ.get(
    "PINTEREST_BOARD_URL",
    "https://www.pinterest.com/tissugeorgia/laptop-bags/",
)


def main() -> None:
    token = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
    print("=" * 60)
    print("Pinterest Client — Stage 3 Test")
    print("=" * 60)
    print(f"Token: {token[:20]}..." if token else "Token: NOT SET")
    print(f"Board: {BOARD_URL}")
    print()

    # ------------------------------------------------------------------
    print("=" * 60)
    print("Test 1: List boards")
    print("=" * 60)
    boards = get_user_boards()
    if boards:
        print(f"Found {len(boards)} boards:")
        for b in boards:
            print(f"  - {b['name']}: {b.get('pin_count', '?')} pins")
            print(f"    ID:  {b['id']}")
            print(f"    URL: {b.get('url', 'N/A')}")
    else:
        print("❌ No boards returned (check token)")

    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Test 2: Get random pin from laptop-bags board")
    print("=" * 60)
    result = get_random_pin(board_url=BOARD_URL, tenant_id="tissu")

    first_pin_id = None
    if result["success"]:
        first_pin_id = result["pin_id"]
        print(f"✅ Got pin:   {result['pin_id']}")
        print(f"📸 Image URL: {result['image_url']}")
        print(f"🔗 Pin URL:   {result['pin_url']}")
        print(f"💬 Alt text:  {result.get('alt_text') or 'N/A'}")
        print()
        print("👀 Open the image URL in browser to verify it works!")
    else:
        print(f"❌ Error: {result['error']}")

    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("Test 3: Run again — should NOT return same pin (variety)")
    print("=" * 60)
    result2 = get_random_pin(board_url=BOARD_URL, tenant_id="tissu")
    if result2["success"]:
        if first_pin_id and result2["pin_id"] != first_pin_id:
            print(f"✅ Different pin returned: {result2['pin_id']}")
        elif not first_pin_id:
            print(f"✅ Got pin: {result2['pin_id']}")
        else:
            print(f"⚠️  Same pin returned (board may have very few pins)")
        print(f"📸 Image URL: {result2['image_url']}")
    else:
        print(f"❌ Error: {result2['error']}")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
