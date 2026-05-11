"""Unit tests for orchestrator — services + DB mocked (no Flask app required)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_bag_agent.ai_content.services import orchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flask_app():
    """Minimal Flask app + in-memory SQLite for orchestrator tests."""
    from ai_bag_agent import create_app
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        from ai_bag_agent.extensions import db
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_bag(flask_app):
    from ai_bag_agent.extensions import db
    from ai_bag_agent.ai_content.models import BagQueue
    bag = BagQueue(
        bag_name="Test Bag",
        image_path="https://res.cloudinary.com/x/y.jpg",
        custom_prompt="extra style",
        reference_url="https://i.pinimg.com/736x/aa/bb.jpg",  # manual override
        status="pending",
        sort_order=1,
    )
    db.session.add(bag)
    db.session.commit()
    return bag


# ---------------------------------------------------------------------------
# run_generate_job
# ---------------------------------------------------------------------------

class TestRunGenerateJob:
    def test_no_pending_bags_returns_no_bags(self, flask_app):
        result = orchestrator.run_generate_job(tenant_id="default")
        assert result["success"] is False
        assert "No bags" in result["error"]

    def test_full_pipeline_success(self, flask_app, sample_bag):
        with patch.object(orchestrator.ai_generator, "generate_image") as gen, \
             patch.object(orchestrator.cloudinary_svc, "upload_generated_image") as up, \
             patch.object(orchestrator, "send_approval_request_sync") as tg:
            gen.return_value = {
                "success": True, "generated_url": "https://kie/raw.png",
                "local_path": "/tmp/x.png", "prompt_used": "p", "error": None,
            }
            up.return_value = {"success": True, "public_url": "https://cld/final.jpg"}
            tg.return_value = "12345"

            result = orchestrator.run_generate_job()

        assert result["success"] is True
        assert result["bag_id"] == sample_bag.id
        assert result["approval_id"] is not None
        assert result["telegram_message_id"] == "12345"

        from ai_bag_agent.ai_content.models import BagQueue, PendingApproval
        bag = BagQueue.query.get(sample_bag.id)
        assert bag.status == "done"
        assert bag.processed_at is not None
        approval = PendingApproval.query.get(result["approval_id"])
        assert approval.generated_image_url == "https://cld/final.jpg"
        assert approval.status == "pending"

    def test_kie_failure_marks_bag_failed(self, flask_app, sample_bag):
        with patch.object(orchestrator.ai_generator, "generate_image") as gen:
            gen.return_value = {"success": False, "error": "kie.ai timeout"}
            result = orchestrator.run_generate_job()

        assert result["success"] is False
        assert "kie.ai" in result["error"]

        from ai_bag_agent.ai_content.models import BagQueue
        bag = BagQueue.query.get(sample_bag.id)
        assert bag.status == "failed"

    def test_pinterest_used_when_no_reference_url(self, flask_app):
        from ai_bag_agent.extensions import db
        from ai_bag_agent.ai_content.models import BagQueue
        bag = BagQueue(bag_name="No-ref bag", image_path="https://x/y.jpg",
                       status="pending", sort_order=1)
        db.session.add(bag)
        db.session.commit()

        with patch.object(orchestrator.pinterest_client, "get_random_pin") as pin, \
             patch.object(orchestrator.ai_generator, "generate_image") as gen, \
             patch.object(orchestrator.cloudinary_svc, "upload_generated_image") as up, \
             patch.object(orchestrator, "send_approval_request_sync", return_value="1"):
            pin.return_value = {"success": True, "image_url": "https://pin.jpg",
                                "pin_id": "p_001", "error": None}
            gen.return_value = {"success": True, "generated_url": "https://k.png",
                                "local_path": None, "prompt_used": "p", "error": None}
            up.return_value = {"success": True, "public_url": "https://c.jpg"}

            result = orchestrator.run_generate_job()

        assert result["success"] is True
        pin.assert_called_once()  # Pinterest WAS used since no manual reference_url


# ---------------------------------------------------------------------------
# trigger_for_bag
# ---------------------------------------------------------------------------

class TestTriggerForBag:
    def test_missing_bag_returns_error(self, flask_app):
        result = orchestrator.trigger_for_bag(999)
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_done_status_rejected(self, flask_app, sample_bag):
        sample_bag.status = "done"
        from ai_bag_agent.extensions import db
        db.session.commit()
        result = orchestrator.trigger_for_bag(sample_bag.id)
        assert result["success"] is False
        assert "expected" in result["error"]

    def test_failed_bag_can_be_retriggered(self, flask_app, sample_bag):
        sample_bag.status = "failed"
        from ai_bag_agent.extensions import db
        db.session.commit()
        with patch.object(orchestrator.ai_generator, "generate_image") as gen, \
             patch.object(orchestrator, "send_approval_request_sync", return_value="1"):
            gen.return_value = {"success": True, "generated_url": "https://x.png",
                                "local_path": None, "prompt_used": "p", "error": None}
            result = orchestrator.trigger_for_bag(sample_bag.id)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# run_post_job
# ---------------------------------------------------------------------------

class TestRunPostJob:
    def test_no_approvals_returns_empty(self, flask_app):
        result = orchestrator.run_post_job()
        assert result["success"] is True
        assert result["posted_count"] == 0
        assert result["failed_count"] == 0

    def test_posts_approved_approvals(self, flask_app, sample_bag):
        from ai_bag_agent.extensions import db
        from ai_bag_agent.ai_content.models import PendingApproval

        a = PendingApproval(
            tenant_id="default", bag_queue_id=sample_bag.id,
            generated_image_url="https://x/y.jpg", status="approved",
        )
        db.session.add(a)
        db.session.commit()

        with patch.object(orchestrator.social_poster, "post_to_both") as posty:
            posty.return_value = {
                "success": True, "fb_status": "success", "ig_status": "success",
                "fb_post_id": "fb_1", "ig_post_id": "ig_1", "error": None,
                "post_log_id": 1,
            }
            result = orchestrator.run_post_job()

        assert result["posted_count"] == 1
        assert result["failed_count"] == 0
        assert result["results"][0]["fb_post_id"] == "fb_1"

    def test_both_fail_counted_as_failed(self, flask_app, sample_bag):
        from ai_bag_agent.extensions import db
        from ai_bag_agent.ai_content.models import PendingApproval
        a = PendingApproval(tenant_id="default", bag_queue_id=sample_bag.id,
                            generated_image_url="https://x/y.jpg", status="approved")
        db.session.add(a)
        db.session.commit()

        with patch.object(orchestrator.social_poster, "post_to_both") as posty:
            posty.return_value = {
                "success": False, "fb_status": "failed", "ig_status": "failed",
                "fb_post_id": None, "ig_post_id": None, "error": "both failed",
                "post_log_id": 1,
            }
            result = orchestrator.run_post_job()

        assert result["success"] is False
        assert result["failed_count"] == 1
