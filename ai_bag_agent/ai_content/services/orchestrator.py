"""Orchestrator — full generate + post pipelines.

Two entry points scheduled in Stage 10 (also callable manually from admin UI):

    run_generate_job(tenant_id)  — picks next pending bag → Pinterest → kie.ai →
                                   Cloudinary → PendingApproval → Telegram
    run_post_job(tenant_id)      — finds approved approvals → FB + IG → PostLog
    trigger_for_bag(bag_id)      — same as run_generate_job but for one bag

Status flow:
    BagQueue:        pending → processing → done | failed
    PendingApproval: pending → approved | rejected → posted
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..models import BagQueue, PendingApproval
from ...extensions import db
from . import ai_generator, cloudinary_svc, pinterest_client, social_poster
from .telegram_bot import send_approval_request_sync

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generate pipeline
# ---------------------------------------------------------------------------

RECENT_INVENTORY_DAYS = 7  # don't re-pick a product used in the last week


def run_generate_job(tenant_id: str = "default") -> dict:
    """Pick the next bag and run the full generation pipeline.

    Resolution order:
      1. Pending bag manually queued by admin (admin override)
      2. Random in-stock product from the storefront API (auto mode)

    Returns: {success, bag_id, approval_id, error}
    """
    bag = (
        BagQueue.query
        .filter_by(status="pending", tenant_id=tenant_id)
        .order_by(BagQueue.sort_order.asc(), BagQueue.created_at.asc())
        .first()
    )
    if bag is None:
        bag = _pull_bag_from_inventory(tenant_id)

    if bag is None:
        logger.info("Generate job: nothing to do for tenant=%s", tenant_id)
        return {
            "success": False, "bag_id": None, "approval_id": None,
            "error": "No bags in queue and storefront inventory is empty",
        }

    return _run_pipeline_for_bag(bag)


def _pull_bag_from_inventory(tenant_id: str = "default") -> Optional[BagQueue]:
    """Pick a random in-stock product from the storefront API and queue it.

    Skips any product whose name was used in the last RECENT_INVENTORY_DAYS,
    so we don't post the same bag twice in a week. Returns the created
    BagQueue row, or None when the storefront returns nothing usable.
    """
    from .inventory_client import get_random_in_stock_product

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_INVENTORY_DAYS)
    recent_names = {
        r.bag_name for r in BagQueue.query.filter(
            BagQueue.tenant_id == tenant_id,
            BagQueue.created_at >= cutoff,
        ).all()
    }

    product = get_random_in_stock_product(exclude_recent_names=recent_names)
    if product is None:
        return None

    # The /api/storefront/products endpoint exposes both image_front and
    # image_back. We persist both so each generation can alternate between
    # them (one side per generation, never both at once).
    # `image_url` is a legacy fallback for the older /api/products payload.
    front = product.get("image_front") or product.get("image_url")
    back = product.get("image_back")
    if not front:
        logger.warning(
            "Inventory product #%s «%s» has no image_front — skipping",
            product.get("id"), product.get("name"),
        )
        return None

    bag = BagQueue(
        tenant_id=tenant_id,
        bag_name=product["name"],
        image_path=front,
        image_path_open=back,  # back-side photo of the same bag
        status="pending",
        sort_order=0,
    )
    db.session.add(bag)
    db.session.commit()
    logger.info(
        "Pulled bag from inventory: storefront #%s «%s» (back=%s) → BagQueue #%s",
        product.get("id"), product["name"], bool(back), bag.id,
    )
    return bag


def trigger_for_bag(bag_id: int, tenant_id: str = "default") -> dict:
    """Manual trigger for one specific bag (admin UI button)."""
    bag = BagQueue.query.filter_by(id=bag_id, tenant_id=tenant_id).first()
    if bag is None:
        return {"success": False, "bag_id": bag_id, "approval_id": None,
                "error": f"Bag id={bag_id} not found"}
    if bag.status not in ("pending", "failed"):
        return {"success": False, "bag_id": bag_id, "approval_id": None,
                "error": f"Bag status is '{bag.status}', expected 'pending' or 'failed'"}
    return _run_pipeline_for_bag(bag)


def _run_pipeline_for_bag(bag: BagQueue) -> dict:
    """Internal: runs Pinterest → kie.ai → Cloudinary → PendingApproval → Telegram.

    Wrapped end-to-end in try/except so an unexpected exception (DB error,
    missing column, code bug…) is caught, persisted to bag.status='failed'
    and written to /tmp/pipeline-errors.log so /health/db can surface it.
    Without this, an uncaught exception in the background thread leaves the
    bag stuck in 'processing' indefinitely with zero diagnostic.
    """
    try:
        return _run_pipeline_for_bag_inner(bag)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.exception("Pipeline crashed for bag %s", bag.id)
        try:
            from pathlib import Path
            Path("/tmp/pipeline-errors.log").write_text(
                f"bag_id={bag.id} bag_name={bag.bag_name!r}\n{tb}\n",
            )
        except Exception:
            pass
        return _fail(bag, f"unhandled exception: {exc}")


def _run_pipeline_for_bag_inner(bag: BagQueue) -> dict:
    bag_id = bag.id
    tenant_id = bag.tenant_id
    bag.status = "processing"
    db.session.commit()

    # ---- 1. Reference image (manual override > Pinterest) ----------------
    if bag.reference_url:
        reference_url = bag.reference_url
        reference_pin_id = None
        logger.info("Bag %s: using manual reference_url", bag_id)
    else:
        board_url = os.environ.get("PINTEREST_BOARD_URL", "")
        pin = pinterest_client.get_random_pin(
            board_url=board_url,
            tenant_id=tenant_id,
            exclude_recent_days=0,
        )
        if not pin["success"]:
            return _fail(bag, f"Pinterest: {pin['error']}")
        reference_url = pin["image_url"]
        reference_pin_id = pin.get("pin_id")

    # ---- 2. Pick front OR back (never both) and call kie.ai -----------------
    # Each generation uses ONE side of the bag — alternates based on how many
    # approvals already exist for the same bag_name. The model gets that side
    # + the Pinterest reference, never both front/back together.
    primary_url, chosen_side = _pick_primary_side(bag)
    gen = ai_generator.generate_image(
        bag_image_path=primary_url,
        reference_image_url=reference_url,
        custom_prompt=bag.custom_prompt or "",
        tenant_id=tenant_id,
    )
    if not gen["success"]:
        return _fail(bag, f"kie.ai: {gen['error']}")

    # ---- 3. Cloudinary upload (replace raw kie.ai URL with permanent one) ----
    final_url = gen["generated_url"]
    if gen.get("local_path"):
        up = cloudinary_svc.upload_generated_image(gen, tenant_id=tenant_id)
        if up.get("success"):
            final_url = up["public_url"]
        else:
            logger.warning("Cloudinary upload failed for bag %s — using raw kie.ai URL: %s",
                           bag_id, up.get("error"))

    # ---- 4. PendingApproval row -----------------------------------------
    # Captions are intentionally left empty — admin writes them via Telegram
    # (reply / ✏️ Edit caption) or the web editor before posting. social_poster
    # falls back to the templated default if both fields are still empty at
    # post time. The caption_generator service is still available manually via
    # /admin/approvals/<id>/edit "Regenerate with AI" button.
    # Tag the row with which side we used so _pick_primary_side can rotate
    # correctly next time. Prepended to the model prompt so it stays visible
    # in the admin diff and doesn't need a schema migration.
    side_tag = f"side={chosen_side}"
    prompt_used = f"{side_tag}\n{gen.get('prompt_used', '')}".strip()
    approval = PendingApproval(
        tenant_id=tenant_id,
        bag_queue_id=bag_id,
        reference_pin_id=reference_pin_id,
        reference_url=reference_url,
        generated_image_url=final_url,
        prompt_used=prompt_used,
        status="pending",
        regeneration_count=0,
    )
    db.session.add(approval)
    bag.status = "done"
    bag.processed_at = datetime.now(timezone.utc)
    db.session.commit()
    approval_id = approval.id

    # ---- 5. Telegram notification ---------------------------------------
    message_id = send_approval_request_sync(approval_id, tenant_id=tenant_id)
    if message_id is None:
        logger.warning("Bag %s: PendingApproval %s created but Telegram send failed",
                       bag_id, approval_id)

    return {
        "success": True,
        "bag_id": bag_id,
        "approval_id": approval_id,
        "telegram_message_id": message_id,
        "error": None,
    }


def _pick_primary_side(bag: BagQueue) -> tuple[str, str]:
    """Return (image_url, side_label) for the SINGLE bag photo this run.

    Alternates between bag.image_path (front) and bag.image_path_open (back)
    so the social feed cycles through both views across runs. Picks the side
    with FEWER prior approvals (counted across every BagQueue row with the
    same name, so storefront re-pulls share the same cycle).

    Falls back to ("<front>", "front") when there is no back photo.
    """
    if not bag.image_path_open:
        return bag.image_path, "front"

    same_name_bag_ids = [
        b.id for b in BagQueue.query.filter_by(
            bag_name=bag.bag_name, tenant_id=bag.tenant_id,
        ).all()
    ]
    rows = PendingApproval.query.filter(
        PendingApproval.bag_queue_id.in_(same_name_bag_ids),
    ).all() if same_name_bag_ids else []

    front_count = sum(1 for r in rows if (r.prompt_used or "").startswith("side=front"))
    back_count = sum(1 for r in rows if (r.prompt_used or "").startswith("side=back"))
    # Historical rows have no side marker — treat them as front (the previous
    # default) so the next pick leans toward back.
    front_count += sum(
        1 for r in rows
        if not (r.prompt_used or "").startswith("side=")
    )

    chosen_side = "back" if back_count < front_count else "front"
    chosen_url = bag.image_path_open if chosen_side == "back" else bag.image_path
    logger.info(
        "Bag %s «%s»: picked side=%s (front_used=%d, back_used=%d)",
        bag.id, bag.bag_name, chosen_side, front_count, back_count,
    )
    return chosen_url, chosen_side


def _fail(bag: BagQueue, error: str) -> dict:
    logger.error("Bag %s failed: %s", bag.id, error)
    bag.status = "failed"
    bag.processed_at = datetime.now(timezone.utc)
    db.session.commit()
    return {
        "success": False,
        "bag_id": bag.id,
        "approval_id": None,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Post pipeline
# ---------------------------------------------------------------------------

def run_post_job(tenant_id: str = "default") -> dict:
    """Post all approved-but-not-yet-posted approvals to FB + IG.

    Returns: {success, posted_count, failed_count, results}
    """
    approvals = (
        PendingApproval.query
        .filter_by(status="approved", tenant_id=tenant_id)
        .order_by(PendingApproval.created_at.asc())
        .all()
    )
    if not approvals:
        logger.info("Post job: no approved approvals for tenant=%s", tenant_id)
        return {"success": True, "posted_count": 0, "failed_count": 0, "results": []}

    results = []
    posted = 0
    failed = 0
    for approval in approvals:
        result = social_poster.post_to_both(approval.id, tenant_id=tenant_id)
        results.append({
            "approval_id": approval.id,
            "success": result["success"],
            "fb_status": result["fb_status"],
            "ig_status": result["ig_status"],
            "fb_post_id": result["fb_post_id"],
            "ig_post_id": result["ig_post_id"],
            "error": result.get("error"),
        })
        if result["success"]:
            posted += 1
        else:
            failed += 1

    logger.info("Post job: %d posted, %d failed (tenant=%s)", posted, failed, tenant_id)
    return {
        "success": failed == 0,
        "posted_count": posted,
        "failed_count": failed,
        "results": results,
    }


def retry_post(approval_id: int, tenant_id: str = "default") -> dict:
    """Manually retry a single approval whose previous post attempt failed."""
    approval = PendingApproval.query.filter_by(
        id=approval_id, tenant_id=tenant_id,
    ).first()
    if approval is None:
        return {"success": False, "error": f"Approval {approval_id} not found"}
    if approval.status != "approved":
        return {"success": False,
                "error": f"Approval status is '{approval.status}', expected 'approved'"}
    return social_poster.post_to_both(approval_id, tenant_id=tenant_id)


def regenerate_approval(approval_id: int, extra_prompt: str = "") -> dict:
    """Run the regen pipeline for an approval + push the new one to Telegram.

    Wraps the helper that powers the 🔄 / 🎨 buttons in Telegram so the web
    UI can call exactly the same code path.
    """
    from .telegram_bot import _blocking_regenerate, send_approval_request_sync
    try:
        new_id = _blocking_regenerate(approval_id, extra_prompt)
    except Exception as exc:
        logger.exception("Regenerate (web) failed for approval %s", approval_id)
        return {"success": False, "error": str(exc), "new_approval_id": None}

    if new_id is None:
        return {"success": False, "error": "Regeneration returned no result",
                "new_approval_id": None}

    message_id = send_approval_request_sync(new_id)
    return {
        "success": True,
        "new_approval_id": new_id,
        "telegram_message_id": message_id,
        "error": None,
    }
