#!/usr/bin/env python3
"""Stage 5 manual test — Telegram approval workflow.

Usage:
    source venv/bin/activate
    python scripts/test_telegram.py

What it does:
    1. Creates (or reuses) a test BagQueue + PendingApproval row in the DB
    2. Starts the Flask app + Telegram bot (background thread)
    3. Sends an approval request to your Telegram chat
    4. Leaves polling running so you can press ✅ / ❌ / 🔄

Press Ctrl+C to stop.
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

# Sanity check
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
if not TOKEN or not CHAT_ID:
    print("❌ TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
    sys.exit(1)

# Test image (any public URL works for visual demo)
TEST_GENERATED_URL = (
    "https://res.cloudinary.com/dw2yuqjrr/image/upload/v1777654735/"
    "tissu/uploads/extra_TP11_20260501165855.jpg"
)
TEST_REFERENCE_URL = "https://www.pinterest.com/tissugeorgia/laptop-bags/"


def main() -> None:
    print("=" * 60)
    print("Stage 5: Telegram Bot — Manual Test")
    print("=" * 60)
    print(f"Bot token: {TOKEN[:15]}...")
    print(f"Chat ID:   {CHAT_ID}")
    print()

    from ai_bag_agent import create_app
    from ai_bag_agent.extensions import db
    from ai_bag_agent.ai_content.models import BagQueue, PendingApproval
    from ai_bag_agent.ai_content.services.telegram_bot import send_approval_request_sync

    app = create_app()
    with app.app_context():
        # Reuse a pending approval if one exists, otherwise create a fresh one
        approval = (
            db.session.query(PendingApproval)
            .filter_by(status="pending")
            .order_by(PendingApproval.id.desc())
            .first()
        )

        if approval is None:
            print("Step 1: Creating test BagQueue + PendingApproval rows...")
            bag = BagQueue(
                bag_name="Test Bag — Telegram Stage 5",
                image_path=TEST_GENERATED_URL,
                custom_prompt="",
                status="processing",
            )
            db.session.add(bag)
            db.session.flush()

            approval = PendingApproval(
                bag_queue_id=bag.id,
                tenant_id="default",
                generated_image_url=TEST_GENERATED_URL,
                reference_url=TEST_REFERENCE_URL,
                prompt_used="(test prompt)",
                status="pending",
                regeneration_count=0,
            )
            db.session.add(approval)
            db.session.commit()
            print(f"   ✅ Created BagQueue id={bag.id}, PendingApproval id={approval.id}")
        else:
            print(f"Step 1: Reusing existing pending approval id={approval.id}")

        approval_id = approval.id

    # ------------------------------------------------------------------
    print()
    print("Step 2: Sending approval request to Telegram...")
    message_id = send_approval_request_sync(approval_id)

    if message_id is None:
        print("❌ Telegram send failed. Check logs above.")
        sys.exit(1)

    print(f"   ✅ Sent — message_id={message_id}")
    print()
    print("Step 3: Bot is now polling for button clicks.")
    print("        Open Telegram and try the buttons:")
    print("          ✅ Approve  → DB status = 'approved', keyboard removed")
    print("          ❌ Reject   → DB status = 'rejected', keyboard removed")
    print("          🔄 Regenerate → new pipeline runs, new message arrives")
    print()
    print("        Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        while True:
            time.sleep(2)
            with app.app_context():
                a = db.session.get(PendingApproval, approval_id)
                if a and a.status != "pending":
                    print(f"\n📥 Status changed to: {a.status}")
                    if a.responded_at:
                        print(f"   at {a.responded_at.isoformat()}")
                    # Don't exit — keep polling so 🔄 regeneration can still work
                    approval_id = -1  # stop watching this one
    except KeyboardInterrupt:
        print("\n\nStopping…")

    from ai_bag_agent.ai_content.services.telegram_bot import shutdown_bot
    shutdown_bot()
    print("Bot stopped.")


if __name__ == "__main__":
    main()
