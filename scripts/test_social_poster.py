#!/usr/bin/env python3
"""Stage 6 manual test — Facebook + Instagram posting.

Usage:
    source venv/bin/activate
    python scripts/test_social_poster.py              # dry-run (no real posts)
    python scripts/test_social_poster.py --live       # actually post (with confirm prompt)

Dry-run shows:
    ✓ Caption preview (FB + IG)
    ✓ Token validation
    ✓ Image URL HEAD check
    ✓ Target FB Page ID + IG Business ID

Live mode:
    ⚠️ Confirmation prompt before posting
    ✓ Actually posts to FB + IG
    ✓ Returns post URLs to verify in browser
"""

from __future__ import annotations

import argparse
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

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Test social poster")
    parser.add_argument("--live", action="store_true",
                        help="Actually post to FB+IG (default: dry-run)")
    parser.add_argument("--approval-id", type=int, default=None,
                        help="Use a specific PendingApproval id (default: latest approved)")
    args = parser.parse_args()

    print("=" * 60)
    print("Social Poster Test —", "LIVE" if args.live else "DRY-RUN")
    print("=" * 60)

    from ai_bag_agent import create_app
    from ai_bag_agent.extensions import db
    from ai_bag_agent.ai_content.models import PendingApproval
    from ai_bag_agent.ai_content.services.social_poster import (
        check_token, generate_caption, post_to_both,
    )

    app = create_app()
    with app.app_context():
        approval = _find_approval(db, PendingApproval, args.approval_id)
        if approval is None:
            print("❌ No approved PendingApproval found in DB.")
            print("   Either approve one via Telegram, or pass --approval-id <id>.")
            sys.exit(1)

        print(f"Using PendingApproval id={approval.id}")
        print(f"   Bag: {approval.bag.bag_name if approval.bag else '?'}")
        print(f"   Image: {approval.generated_image_url[:80]}")
        print()

        # ----------------------------------------------------------
        # Step 1: Token validation
        # ----------------------------------------------------------
        print("Step 1: Validating FB_PAGE_ACCESS_TOKEN…")
        tok = check_token()
        if not tok["valid"]:
            print(f"   ❌ Token error: {tok['error']}")
            sys.exit(1)
        print(f"   ✅ {tok['name']} — expires: {tok['expires_in_days']}")
        print()

        # ----------------------------------------------------------
        # Step 2: Caption preview
        # ----------------------------------------------------------
        print("Step 2: Caption preview")
        fb_cap = generate_caption(approval, "fb")
        ig_cap = generate_caption(approval, "ig")
        print("   --- FB ---")
        for line in fb_cap.split("\n"):
            print(f"   {line}")
        print("   --- IG ---")
        for line in ig_cap.split("\n"):
            print(f"   {line}")
        print()

        # ----------------------------------------------------------
        # Step 3: Image URL reachability
        # ----------------------------------------------------------
        print("Step 3: Checking image URL is publicly reachable…")
        try:
            r = requests.head(approval.generated_image_url, timeout=10, allow_redirects=True)
            if r.status_code < 400:
                print(f"   ✅ HTTP {r.status_code} — Content-Type: {r.headers.get('Content-Type','?')}")
            else:
                print(f"   ⚠️  HTTP {r.status_code}")
        except Exception as exc:
            print(f"   ⚠️  HEAD failed: {exc}")
        print()

        # ----------------------------------------------------------
        # Step 4: Target IDs
        # ----------------------------------------------------------
        print("Step 4: Target accounts")
        print(f"   FB Page ID:           {os.environ.get('FB_PAGE_ID', '(not set)')}")
        print(f"   IG Business Acct ID:  {os.environ.get('IG_BUSINESS_ACCOUNT_ID', '(not set)')}")
        print(f"   Graph API version:    {os.environ.get('META_API_VERSION', 'v21.0')}")
        print()

        # ----------------------------------------------------------
        # Dry-run stops here
        # ----------------------------------------------------------
        if not args.live:
            print("=" * 60)
            print("DRY-RUN complete. No posts were made.")
            print("Run with --live to actually post.")
            print("=" * 60)
            return

        # ----------------------------------------------------------
        # Step 5: Confirmation prompt
        # ----------------------------------------------------------
        print("⚠️  THIS WILL POST TO LIVE FACEBOOK + INSTAGRAM.")
        confirm = input("    Type YES to confirm: ").strip()
        if confirm != "YES":
            print("Aborted.")
            return

        # ----------------------------------------------------------
        # Step 6: Real post
        # ----------------------------------------------------------
        print()
        print("Posting…")
        result = post_to_both(approval.id, tenant_id="default")

        print()
        print("=" * 60)
        print("RESULT")
        print("=" * 60)
        print(f"Overall: {'✅ SUCCESS' if result['success'] else '❌ BOTH FAILED'}")
        print(f"FB: {result['fb_status']:<8} id={result['fb_post_id']}")
        print(f"IG: {result['ig_status']:<8} id={result['ig_post_id']}")
        if result.get("fb_post_id"):
            print(f"   👉 FB post: https://www.facebook.com/{result['fb_post_id']}")
        if result.get("ig_post_id"):
            print(f"   👉 IG media id: {result['ig_post_id']}")
        if result.get("error"):
            print(f"Error: {result['error']}")
        print("=" * 60)


def _find_approval(db, PendingApproval, approval_id):
    if approval_id is not None:
        return db.session.get(PendingApproval, approval_id)
    # Default: latest approved that hasn't been posted
    return (
        db.session.query(PendingApproval)
        .filter_by(status="approved")
        .order_by(PendingApproval.id.desc())
        .first()
    ) or (
        # Fallback: latest pending (so dry-run works even before approval)
        db.session.query(PendingApproval)
        .filter_by(status="pending")
        .order_by(PendingApproval.id.desc())
        .first()
    )


if __name__ == "__main__":
    main()
