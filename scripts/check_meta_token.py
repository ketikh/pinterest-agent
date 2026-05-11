#!/usr/bin/env python3
"""Validate FB_PAGE_TOKEN — call once after setting up .env.

Usage:
    source venv/bin/activate
    python scripts/check_meta_token.py

Reports:
    ✅ Token valid + expiry (or "never" for non-expiring page tokens)
    ❌ Token invalid + Meta's error message
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

from ai_bag_agent.ai_content.services.social_poster import check_token


def main() -> None:
    print("=" * 60)
    print("Meta Token Validation")
    print("=" * 60)

    result = check_token()

    if not result["valid"]:
        print(f"❌ Token INVALID")
        print(f"   Error: {result['error']}")
        print()
        print("Fix: regenerate FB_PAGE_TOKEN at developers.facebook.com")
        print("     → Tools → Graph API Explorer → Get Page Access Token")
        sys.exit(1)

    print(f"✅ Token VALID")
    print(f"   Account: {result['name']}")
    print(f"   Expires: {result['expires_in_days']} (epoch {result['expires_at']})")

    if result["expires_in_days"] != "never":
        print()
        print("⚠️  This token has a finite expiry.")
        print("    For production, use a long-lived **Page** Access Token (never expires).")
        print("    See: https://developers.facebook.com/docs/facebook-login/access-tokens")

    print("=" * 60)


if __name__ == "__main__":
    main()
