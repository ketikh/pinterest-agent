"""Admin panel routes."""

from __future__ import annotations

import os
import pathlib
import tempfile

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required
from werkzeug.utils import secure_filename

from . import ai_content_bp
from .models import BagQueue, PendingApproval, PostLog, Setting
from ..extensions import db

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@ai_content_bp.route("/")
@ai_content_bp.route("/dashboard")
@login_required
def dashboard():
    queue_count = BagQueue.query.filter_by(status="pending").count()
    pending_count = PendingApproval.query.filter_by(status="pending").count()
    approved_count = PendingApproval.query.filter_by(status="approved").count()
    posted_count = PostLog.query.count()

    return render_template(
        "ai_content/dashboard.html",
        queue_count=queue_count,
        pending_count=pending_count,
        approved_count=approved_count,
        posted_count=posted_count,
    )


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@ai_content_bp.route("/queue")
@login_required
def queue():
    bags = (
        BagQueue.query
        .order_by(BagQueue.sort_order.asc(), BagQueue.created_at.asc())
        .all()
    )
    return render_template("ai_content/queue.html", bags=bags)


@ai_content_bp.route("/queue/upload", methods=["POST"])
@login_required
def queue_upload():
    bag_name = request.form.get("bag_name", "").strip()
    custom_prompt = request.form.get("custom_prompt", "").strip() or None
    reference_url = request.form.get("reference_url", "").strip() or None
    file = request.files.get("bag_image")

    if not bag_name:
        flash("ჩანთის სახელი სავალდებულოა.", "danger")
        return redirect(url_for("ai_content.queue"))

    if not file or not file.filename:
        flash("ფოტო სავალდებულოა.", "danger")
        return redirect(url_for("ai_content.queue"))

    if not _allowed_file(file.filename):
        flash("მხოლოდ JPG, PNG ან WebP ფორმატია დაშვებული.", "danger")
        return redirect(url_for("ai_content.queue"))

    from .services.cloudinary_svc import upload_image
    suffix = pathlib.Path(secure_filename(file.filename)).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        file.save(tmp.name)
        result = upload_image(tmp.name, tenant_id="default", category="bags")
    os.unlink(tmp.name)

    if not result["success"]:
        flash(f"Cloudinary ატვირთვა ვერ მოხდა: {result['error']}", "danger")
        return redirect(url_for("ai_content.queue"))

    last = BagQueue.query.order_by(BagQueue.sort_order.desc()).first()
    next_order = (last.sort_order + 1) if last else 1

    bag = BagQueue(
        bag_name=bag_name,
        image_path=result["public_url"],
        custom_prompt=custom_prompt,
        reference_url=reference_url,
        sort_order=next_order,
    )
    db.session.add(bag)
    db.session.commit()

    flash(f"✅ «{bag_name}» დაემატა რიგს.", "success")
    return redirect(url_for("ai_content.queue"))


@ai_content_bp.route("/queue/<int:bag_id>/trigger", methods=["POST"])
@login_required
def queue_trigger(bag_id: int):
    from .services.orchestrator import trigger_for_bag
    result = trigger_for_bag(bag_id)
    if result["success"]:
        flash(
            f"✅ Pipeline დასრულდა. Approval #{result['approval_id']} შეიქმნა "
            "და Telegram-ში გაიგზავნა.",
            "success",
        )
    else:
        flash(f"❌ Pipeline ჩავარდა: {result.get('error', 'unknown')}", "danger")
    return redirect(url_for("ai_content.queue"))


@ai_content_bp.route("/queue/<int:bag_id>/delete", methods=["POST"])
@login_required
def queue_delete(bag_id: int):
    bag = BagQueue.query.get_or_404(bag_id)
    if bag.status != "pending":
        flash("მხოლოდ pending სტატუსის ჩანთა შეიძლება წაიშალოს.", "warning")
        return redirect(url_for("ai_content.queue"))
    name = bag.bag_name
    db.session.delete(bag)
    db.session.commit()
    flash(f"«{name}» წაიშალა.", "success")
    return redirect(url_for("ai_content.queue"))


@ai_content_bp.route("/queue/reorder", methods=["POST"])
@login_required
def queue_reorder():
    order = request.json.get("order", [])
    for position, bag_id in enumerate(order, start=1):
        BagQueue.query.filter_by(id=bag_id).update({"sort_order": position})
    db.session.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

@ai_content_bp.route("/approvals")
@login_required
def approvals():
    status_filter = request.args.get("status", "all")
    query = PendingApproval.query
    if status_filter != "all":
        query = query.filter_by(status=status_filter)
    approvals = (
        query.order_by(PendingApproval.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "ai_content/approvals.html",
        approvals=approvals,
        status_filter=status_filter,
    )


@ai_content_bp.route("/approvals/<int:approval_id>/retry", methods=["POST"])
@login_required
def approval_retry(approval_id: int):
    from .services.orchestrator import retry_post
    result = retry_post(approval_id)
    if result.get("success"):
        flash("✅ ხელახლა გამოქვეყნდა.", "success")
    else:
        flash(f"❌ ვერ მოხერხდა: {result.get('error', 'unknown')}", "danger")
    return redirect(url_for("ai_content.approvals"))


@ai_content_bp.route("/approvals/<int:approval_id>/edit", methods=["GET", "POST"])
@login_required
def approval_edit(approval_id: int):
    approval = PendingApproval.query.get_or_404(approval_id)

    if request.method == "POST":
        approval.fb_caption = (request.form.get("fb_caption", "") or "").strip() or None
        approval.ig_caption = (request.form.get("ig_caption", "") or "").strip() or None
        db.session.commit()
        flash("✅ Captions saved.", "success")
        return redirect(url_for("ai_content.approvals"))

    return render_template("ai_content/approval_edit.html", approval=approval)


@ai_content_bp.route("/approvals/<int:approval_id>/regenerate-captions", methods=["POST"])
@login_required
def approval_regenerate_captions(approval_id: int):
    approval = PendingApproval.query.get_or_404(approval_id)
    bag = approval.bag
    if bag is None:
        flash("❌ Bag-ი დაკარგულია.", "danger")
        return redirect(url_for("ai_content.approval_edit", approval_id=approval_id))

    from .services.caption_generator import generate_captions
    result = generate_captions(
        bag_name=bag.bag_name,
        custom_prompt=bag.custom_prompt or "",
        reference_url=approval.reference_url or "",
    )
    if result["success"]:
        approval.fb_caption = result["fb_caption"]
        approval.ig_caption = result["ig_caption"]
        db.session.commit()
        flash("✨ Captions regenerated.", "success")
    else:
        flash(f"❌ Caption regeneration failed: {result['error']}", "danger")
    return redirect(url_for("ai_content.approval_edit", approval_id=approval_id))


# ---------------------------------------------------------------------------
# Posts (history)
# ---------------------------------------------------------------------------

@ai_content_bp.route("/posts")
@login_required
def posts():
    posts = (
        PostLog.query
        .order_by(PostLog.posted_at.desc())
        .limit(100)
        .all()
    )
    return render_template("ai_content/posts.html", posts=posts)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_SETTING_KEYS = (
    "global_prompt_template",
    "fb_caption_template",
    "ig_caption_template",
)

_CREDENTIAL_KEYS = (
    ("KIE_AI_API_KEY", "kie.ai"),
    ("CLOUDINARY_API_KEY", "Cloudinary"),
    ("PINTEREST_ACCESS_TOKEN", "Pinterest"),
    ("TELEGRAM_BOT_TOKEN", "Telegram bot"),
    ("TELEGRAM_CHAT_ID", "Telegram chat"),
    ("FB_PAGE_TOKEN", "Facebook token"),
    ("FB_PAGE_ID", "Facebook page"),
    ("IG_BUSINESS_ACCOUNT_ID", "Instagram"),
)


@ai_content_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings_view():
    if request.method == "POST":
        for key in _SETTING_KEYS:
            value = request.form.get(key, "").strip()
            Setting.set(key, value)
        flash("✅ Settings saved.", "success")
        return redirect(url_for("ai_content.settings_view"))

    # Show the hardcoded defaults pre-filled when admin hasn't customised yet —
    # makes hashtags visible and editable instead of hiding behind "default".
    from .services.social_poster import DEFAULT_FB_TEMPLATE, DEFAULT_IG_TEMPLATE
    from .config.prompt_template import GLOBAL_SYSTEM_PROMPT

    defaults = {
        "global_prompt_template": GLOBAL_SYSTEM_PROMPT,
        "fb_caption_template": DEFAULT_FB_TEMPLATE,
        "ig_caption_template": DEFAULT_IG_TEMPLATE,
    }
    values = {
        key: (Setting.get(key, default="") or defaults[key])
        for key in _SETTING_KEYS
    }
    credentials = [
        (label, bool(os.environ.get(env_key)))
        for env_key, label in _CREDENTIAL_KEYS
    ]
    return render_template(
        "ai_content/settings.html",
        values=values,
        credentials=credentials,
    )


# ---------------------------------------------------------------------------
# Manual job triggers (synchronous — admin sees result after pipeline finishes)
# ---------------------------------------------------------------------------

@ai_content_bp.route("/jobs/run-generate", methods=["POST"])
@login_required
def jobs_run_generate():
    from .services.orchestrator import run_generate_job
    result = run_generate_job()
    if result["success"]:
        flash(
            f"✅ Generate job: bag #{result['bag_id']} → approval "
            f"#{result['approval_id']} (Telegram sent).",
            "success",
        )
    else:
        flash(f"⚠️ Generate job: {result.get('error')}", "warning")
    return redirect(url_for("ai_content.dashboard"))


@ai_content_bp.route("/jobs/run-post", methods=["POST"])
@login_required
def jobs_run_post():
    from .services.orchestrator import run_post_job
    result = run_post_job()
    flash(
        f"✅ Post job: {result['posted_count']} posted, "
        f"{result['failed_count']} failed.",
        "success" if result["success"] else "warning",
    )
    return redirect(url_for("ai_content.dashboard"))
