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
    def test_no_queue_and_empty_inventory_returns_error(self, flask_app):
        with patch("ai_bag_agent.ai_content.services.inventory_client.get_random_in_stock_product",
                   return_value=None):
            result = orchestrator.run_generate_job(tenant_id="default")
        assert result["success"] is False
        assert "inventory" in result["error"].lower() or "queue" in result["error"].lower()

    def test_pulls_from_inventory_when_queue_empty(self, flask_app):
        fake_product = {
            "id": 42,
            "name": "Tissu Large #1",
            "image_url": "https://res.cloudinary.com/x/y.jpg",
            "in_stock": True,
        }
        with patch("ai_bag_agent.ai_content.services.inventory_client.get_random_in_stock_product",
                   return_value=fake_product), \
             patch.object(orchestrator.pinterest_client, "get_random_pin",
                          return_value={"success": True, "image_url": "https://p.jpg",
                                        "pin_id": "p1", "error": None}), \
             patch.object(orchestrator.ai_generator, "generate_image") as gen, \
             patch.object(orchestrator.cloudinary_svc, "upload_image",
                          return_value={"success": True, "public_url": "https://cld/x.jpg"}), \
             patch("ai_bag_agent.ai_content.services.composite.extract_bag_with_alpha",
                   return_value=b"PNG"), \
             patch("ai_bag_agent.ai_content.services.composite.composite_bag_on_scene",
                   return_value=b"JPEG"), \
             patch("ai_bag_agent.ai_content.services.composite.save_bytes_to_tmp",
                   return_value="/tmp/c.jpg"), \
             patch.object(orchestrator, "send_approval_request_sync", return_value="42"):
            gen.return_value = {"success": True, "generated_url": "https://k.png",
                                "local_path": "/tmp/x.png", "prompt_used": "p", "error": None}
            result = orchestrator.run_generate_job()

        assert result["success"] is True
        # Verify a BagQueue row was created from the storefront product
        from ai_bag_agent.ai_content.models import BagQueue
        bag = BagQueue.query.get(result["bag_id"])
        assert bag.bag_name == "Tissu Large #1"
        assert bag.image_path == "https://res.cloudinary.com/x/y.jpg"
        assert bag.status == "done"

    def test_inventory_skips_recent_names(self, flask_app):
        from ai_bag_agent.extensions import db
        from ai_bag_agent.ai_content.models import BagQueue
        # Pretend we already posted this bag yesterday
        old = BagQueue(bag_name="Tissu Large #1",
                       image_path="https://cld/x.jpg",
                       status="done", sort_order=0)
        db.session.add(old)
        db.session.commit()

        captured = {}

        def fake_picker(exclude_recent_names=None):
            captured["excluded"] = exclude_recent_names or set()
            return None  # short-circuit; we only care about the exclusion set

        with patch("ai_bag_agent.ai_content.services.inventory_client.get_random_in_stock_product",
                   side_effect=fake_picker):
            orchestrator.run_generate_job()

        assert "Tissu Large #1" in captured["excluded"]

    def test_full_pipeline_success(self, flask_app, sample_bag):
        with patch.object(orchestrator.ai_generator, "generate_image") as gen, \
             patch.object(orchestrator.cloudinary_svc, "upload_image") as up, \
             patch("ai_bag_agent.ai_content.services.composite.extract_bag_with_alpha",
                   return_value=b"PNG_BYTES"), \
             patch("ai_bag_agent.ai_content.services.composite.composite_bag_on_scene",
                   return_value=b"JPEG_BYTES"), \
             patch("ai_bag_agent.ai_content.services.composite.save_bytes_to_tmp",
                   return_value="/tmp/composite_xxx.jpg"), \
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
             patch.object(orchestrator.cloudinary_svc, "upload_image") as up, \
             patch("ai_bag_agent.ai_content.services.composite.extract_bag_with_alpha",
                   return_value=b"PNG"), \
             patch("ai_bag_agent.ai_content.services.composite.composite_bag_on_scene",
                   return_value=b"JPEG"), \
             patch("ai_bag_agent.ai_content.services.composite.save_bytes_to_tmp",
                   return_value="/tmp/c.jpg"), \
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
             patch.object(orchestrator.cloudinary_svc, "upload_image",
                          return_value={"success": True, "public_url": "https://c.jpg"}), \
             patch("ai_bag_agent.ai_content.services.composite.extract_bag_with_alpha",
                   return_value=b"PNG"), \
             patch("ai_bag_agent.ai_content.services.composite.composite_bag_on_scene",
                   return_value=b"JPEG"), \
             patch("ai_bag_agent.ai_content.services.composite.save_bytes_to_tmp",
                   return_value="/tmp/c.jpg"), \
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

    def test_product_type_filter_posts_only_matching(self, flask_app):
        from ai_bag_agent.extensions import db
        from ai_bag_agent.ai_content.models import BagQueue, PendingApproval

        bagq = BagQueue(bag_name="B", image_path="https://b.jpg",
                        product_type="bag", status="done", sort_order=1)
        neck = BagQueue(bag_name="N", image_path="https://n.jpg",
                        product_type="necklace", status="done", sort_order=2)
        db.session.add_all([bagq, neck])
        db.session.commit()
        ab = PendingApproval(tenant_id="default", bag_queue_id=bagq.id,
                             generated_image_url="https://b/y.jpg", status="approved")
        an = PendingApproval(tenant_id="default", bag_queue_id=neck.id,
                             generated_image_url="https://n/y.jpg", status="approved")
        db.session.add_all([ab, an])
        db.session.commit()
        neck_approval_id = an.id

        with patch.object(orchestrator.social_poster, "post_to_both") as posty:
            posty.return_value = {
                "success": True, "fb_status": "success", "ig_status": "success",
                "fb_post_id": "f", "ig_post_id": "i", "error": None, "post_log_id": 1,
            }
            result = orchestrator.run_post_job(product_type="necklace")

        assert result["posted_count"] == 1
        posty.assert_called_once_with(neck_approval_id, tenant_id="default")


# ---------------------------------------------------------------------------
# run_necklace_generate_job
# ---------------------------------------------------------------------------

class TestRunNecklaceGenerateJob:
    def test_empty_inspirations_returns_error(self, flask_app):
        with patch("ai_bag_agent.ai_content.services.inspirations_client.list_inspirations",
                   return_value=[]):
            result = orchestrator.run_necklace_generate_job()
        assert result["success"] is False
        assert "necklace" in result["error"].lower() or "gallery" in result["error"].lower()

    def test_pulls_necklace_from_inspirations(self, flask_app):
        items = [{"id": 7, "category": "necklace",
                  "image_url": "https://c/n.jpg", "caption": "", "position": 1}]
        with patch("ai_bag_agent.ai_content.services.inspirations_client.list_inspirations",
                   return_value=items), \
             patch.object(orchestrator.pinterest_client, "get_random_pin",
                          return_value={"success": True, "image_url": "https://p.jpg",
                                        "pin_id": "p1", "error": None}), \
             patch.object(orchestrator.ai_generator, "generate_image",
                          return_value={"success": True, "generated_url": "https://k.png",
                                        "local_path": None, "prompt_used": "p", "error": None}), \
             patch.object(orchestrator, "send_approval_request_sync", return_value="55"):
            result = orchestrator.run_necklace_generate_job()

        assert result["success"] is True
        from ai_bag_agent.ai_content.models import BagQueue
        bag = BagQueue.query.get(result["bag_id"])
        assert bag.product_type == "necklace"
        assert bag.image_path == "https://c/n.jpg"
        assert bag.bag_name == "Necklace #7"
        assert bag.status == "done"

    def test_necklace_uses_jewelry_board(self, flask_app):
        items = [{"id": 9, "image_url": "https://c/n.jpg", "caption": "Blue", "position": 1}]
        with patch.dict("os.environ", {"PINTEREST_BOARD_URL_JEWELRY": "https://pin/jewelry"}), \
             patch("ai_bag_agent.ai_content.services.inspirations_client.list_inspirations",
                   return_value=items), \
             patch.object(orchestrator.pinterest_client, "get_random_pin") as pin, \
             patch.object(orchestrator.ai_generator, "generate_image",
                          return_value={"success": True, "generated_url": "https://k.png",
                                        "local_path": None, "prompt_used": "p", "error": None}), \
             patch.object(orchestrator, "send_approval_request_sync", return_value="1"):
            pin.return_value = {"success": True, "image_url": "https://p.jpg",
                                "pin_id": "p1", "error": None}
            orchestrator.run_necklace_generate_job()

        # The jewelry board URL (not the bag board) must be used for necklaces.
        _, kwargs = pin.call_args
        assert kwargs.get("board_url") == "https://pin/jewelry"
