"""Dry-run the regenerate path with stubbed external services.

Replaces kie.ai (generate_image), Pinterest (get_random_pin), Cloudinary
(upload_generated_image) and Telegram (send_approval_request_sync) so we
can confirm the *orchestration* glue still works without spending credits
or pestering the admin chat.
"""

from __future__ import annotations

import logging
import os
import sys
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv()
# Disable real Telegram bot init — we'll patch send_approval_request_sync.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ.setdefault("FLASK_SECRET_KEY", "x")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from ai_bag_agent import create_app  # noqa: E402

app = create_app()


def fake_get_random_pin(*args, **kwargs):
    print("  → stubbed get_random_pin called")
    return {
        "success": True,
        "image_url": "https://example.com/fake-pinterest-ref.jpg",
        "pin_id": "stub-pin-1",
        "error": None,
    }


def fake_generate_image(*args, **kwargs):
    open_url = kwargs.get("bag_image_open_url")
    print(f"  → stubbed generate_image called: bag={kwargs.get('bag_image_path')}, "
          f"ref={kwargs.get('reference_image_url')}, "
          f"open={open_url or '(none)'}, prompt_len="
          f"{len(kwargs.get('custom_prompt', ''))}")
    return {
        "success": True,
        "generated_url": "https://example.com/fake-generated.png",
        "local_path": "/tmp/fake.jpg",
        "model_used": "stub",
        "generation_time_sec": 0.1,
        "prompt_used": "stub-prompt",
        "error": None,
    }


def fake_upload(*args, **kwargs):
    return {"success": True, "public_url": "https://res.cloudinary.com/fake/upload.jpg"}


def fake_send_telegram(approval_id, *args, **kwargs):
    print(f"  → stubbed send_approval_request_sync(approval_id={approval_id})")
    return "fake-tg-msg-123"


def main() -> int:
    with app.app_context():
        from ai_bag_agent.ai_content.models import BagQueue, PendingApproval
        from ai_bag_agent.extensions import db

        approval = (
            PendingApproval.query
            .filter(PendingApproval.status.in_(["pending", "rejected"]))
            .order_by(PendingApproval.id.desc())
            .first()
        )
        if approval is None:
            # Create one so we have something to regen
            bag = BagQueue(
                bag_name="Dryrun test bag",
                image_path="https://res.cloudinary.com/example/sample.jpg",
                status="done",
                sort_order=999,
            )
            db.session.add(bag)
            db.session.commit()
            approval = PendingApproval(
                bag_queue_id=bag.id,
                generated_image_url="https://res.cloudinary.com/example/old.jpg",
                reference_url="https://example.com/old-ref.jpg",
                status="rejected",
                regeneration_count=0,
            )
            db.session.add(approval)
            db.session.commit()
            print(f"Created test approval #{approval.id}")
        approval_id = approval.id
        regen_before = approval.regeneration_count
        print(f"Testing regen on approval #{approval_id} "
              f"(status={approval.status}, regen_count={regen_before})")

    # Patch the Telegram bot's _flask_app since we skipped init_telegram_bot.
    from ai_bag_agent.ai_content.services import telegram_bot as tg
    tg._flask_app = app

    patches = [
        patch("ai_bag_agent.ai_content.services.telegram_bot.get_random_pin",
              fake_get_random_pin, create=True),
        patch("ai_bag_agent.ai_content.services.telegram_bot.generate_image",
              fake_generate_image, create=True),
        patch("ai_bag_agent.ai_content.services.telegram_bot.upload_generated_image",
              fake_upload, create=True),
        patch("ai_bag_agent.ai_content.services.pinterest_client.get_random_pin",
              fake_get_random_pin),
        patch("ai_bag_agent.ai_content.services.ai_generator.generate_image",
              fake_generate_image),
        patch("ai_bag_agent.ai_content.services.cloudinary_svc.upload_generated_image",
              fake_upload),
        patch("ai_bag_agent.ai_content.services.telegram_bot.send_approval_request_sync",
              fake_send_telegram),
        patch("ai_bag_agent.ai_content.services.orchestrator.send_approval_request_sync",
              fake_send_telegram),
    ]
    for p in patches:
        p.start()

    # Direct test of the regen helper used by both web button and Telegram button.
    from ai_bag_agent.ai_content.services.orchestrator import regenerate_approval
    print("\n=== Test 1: regen without extra prompt ===")
    result = regenerate_approval(approval_id, "")
    print(f"Result: {result}")
    assert result["success"], f"Plain regen failed: {result}"

    new_id = result["new_approval_id"]
    with app.app_context():
        from ai_bag_agent.ai_content.models import PendingApproval
        new = PendingApproval.query.get(new_id)
        print(f"  new approval #{new.id} regen_count={new.regeneration_count} "
              f"(expected {regen_before + 1})")
        assert new.regeneration_count == regen_before + 1

    print("\n=== Test 2: regen WITH extra prompt ===")
    result2 = regenerate_approval(new_id, "Outdoor setting, golden hour, darker shadows")
    print(f"Result: {result2}")
    assert result2["success"], f"Prompt regen failed: {result2}"

    for p in patches:
        p.stop()

    print("\n✅ Regenerate orchestrator path works end-to-end (stubbed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
