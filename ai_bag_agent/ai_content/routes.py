"""Admin panel routes."""

from __future__ import annotations

import os
import pathlib
import tempfile

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required
from werkzeug.utils import secure_filename

from . import ai_content_bp
from .models import BagQueue, PendingApproval, PostLog
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
