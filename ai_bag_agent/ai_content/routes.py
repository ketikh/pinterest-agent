"""Admin panel routes."""

from __future__ import annotations

import os
import pathlib
import tempfile

import secrets
from datetime import datetime, timezone

from flask import flash, redirect, render_template, request, session, url_for
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
    processing_count = BagQueue.query.filter_by(status="processing").count()
    pending_count = PendingApproval.query.filter_by(status="pending").count()
    approved_count = PendingApproval.query.filter_by(status="approved").count()
    posted_count = PostLog.query.count()

    # Inline lists for the control-center view
    processing_bags = (
        BagQueue.query.filter_by(status="processing")
        .order_by(BagQueue.created_at.desc()).limit(5).all()
    )
    pending_approvals = (
        PendingApproval.query.filter_by(status="pending")
        .order_by(PendingApproval.created_at.desc()).limit(10).all()
    )
    scheduled_approvals = (
        PendingApproval.query.filter_by(status="approved")
        .order_by(PendingApproval.created_at.asc()).limit(10).all()
    )
    recent_posts = (
        PostLog.query.order_by(PostLog.posted_at.desc()).limit(5).all()
    )

    from .services.scheduler import next_run_times
    next_runs = next_run_times()

    return render_template(
        "ai_content/dashboard.html",
        queue_count=queue_count,
        processing_count=processing_count,
        pending_count=pending_count,
        approved_count=approved_count,
        posted_count=posted_count,
        processing_bags=processing_bags,
        pending_approvals=pending_approvals,
        scheduled_approvals=scheduled_approvals,
        recent_posts=recent_posts,
        next_morning=next_runs["morning"],
        next_evening=next_runs["evening"],
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
    file_open = request.files.get("bag_image_open")

    if not bag_name:
        flash("ჩანთის სახელი სავალდებულოა.", "danger")
        return redirect(url_for("ai_content.queue"))

    if not file or not file.filename:
        flash("ფოტო სავალდებულოა.", "danger")
        return redirect(url_for("ai_content.queue"))

    if not _allowed_file(file.filename):
        flash("მხოლოდ JPG, PNG ან WebP ფორმატია დაშვებული.", "danger")
        return redirect(url_for("ai_content.queue"))

    if file_open and file_open.filename and not _allowed_file(file_open.filename):
        flash("გახსნილი ფოტოც მხოლოდ JPG, PNG ან WebP ფორმატში.", "danger")
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

    # Optional second photo (opened bag). Uploaded the same way; failure here
    # is non-fatal — the closed photo still works on its own.
    image_path_open = None
    if file_open and file_open.filename:
        suffix2 = pathlib.Path(secure_filename(file_open.filename)).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix2, delete=False) as tmp2:
            file_open.save(tmp2.name)
            result_open = upload_image(tmp2.name, tenant_id="default", category="bags")
        os.unlink(tmp2.name)
        if result_open["success"]:
            image_path_open = result_open["public_url"]
        else:
            flash(
                f"⚠️ გახსნილი ფოტო Cloudinary-ზე ვერ ავიდა: {result_open['error']}. "
                "გენერაცია გრძელდება მხოლოდ დახურული ფოტოთი.",
                "warning",
            )

    last = BagQueue.query.order_by(BagQueue.sort_order.desc()).first()
    next_order = (last.sort_order + 1) if last else 1

    bag = BagQueue(
        bag_name=bag_name,
        image_path=result["public_url"],
        image_path_open=image_path_open,
        custom_prompt=custom_prompt,
        reference_url=reference_url,
        sort_order=next_order,
    )
    db.session.add(bag)
    db.session.commit()

    # "Generate immediately" — pipeline runs in a background thread so the
    # upload modal closes right away and the queue page can show live status.
    generate_now = request.form.get("generate_now", "").lower() in ("on", "true", "1")
    if generate_now:
        import threading
        from flask import current_app
        app = current_app._get_current_object()
        bag_id = bag.id

        def _run_pipeline_async():
            with app.app_context():
                from .services.orchestrator import trigger_for_bag
                trigger_for_bag(bag_id)  # status persists to DB; logs handle errors

        threading.Thread(target=_run_pipeline_async, daemon=True).start()
        flash(
            f"⏳ «{bag_name}» — generation started. Refresh the queue or watch it live.",
            "info",
        )
        return redirect(url_for("ai_content.queue"))

    flash(f"✅ «{bag_name}» დაემატა რიგს. ▶️ Trigger დააჭირე გენერაციისთვის.",
          "success")
    return redirect(url_for("ai_content.queue"))


@ai_content_bp.route("/queue/<int:bag_id>/trigger", methods=["POST"])
@login_required
def queue_trigger(bag_id: int):
    # Pre-flight: confirm the bag exists and is in a trigger-able state so we
    # don't silently spawn a thread for a missing/done bag.
    bag = BagQueue.query.get_or_404(bag_id)
    # Bags stuck in 'processing' for longer than this are treated as orphaned
    # (worker restart, dead background thread) and reset to 'failed' so a
    # fresh trigger can re-run them. kie.ai's longest poll budget is 300s, so
    # 10 minutes is well past any legitimate in-flight pipeline.
    stuck_threshold_min = 10
    if bag.status == "processing":
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_threshold_min)
        ref_time = bag.processed_at or bag.created_at
        if ref_time and ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        if ref_time and ref_time < cutoff:
            bag.status = "failed"
            db.session.commit()
            flash(
                f"♻️ «{bag.bag_name}» იყო ჩარჩენილი processing-ში >{stuck_threshold_min}წ "
                "— failed-ში გადავიყვანე და თავიდან ვუშვებ.",
                "info",
            )
        else:
            flash(
                f"⏳ «{bag.bag_name}» ჯერ აქტიურად ცადება ({stuck_threshold_min}წ-ის ფანჯარაში). "
                "დაელოდე ან ცადე ცოტა მერე.",
                "warning",
            )
            return redirect(url_for("ai_content.queue"))
    elif bag.status not in ("pending", "failed"):
        flash(f"⚠️ «{bag.bag_name}» status='{bag.status}' — only pending/failed bags can be triggered.",
              "warning")
        return redirect(url_for("ai_content.queue"))

    import threading
    from flask import current_app
    app = current_app._get_current_object()

    def _run_pipeline_async():
        with app.app_context():
            from .services.orchestrator import trigger_for_bag
            trigger_for_bag(bag_id)

    threading.Thread(target=_run_pipeline_async, daemon=True).start()
    flash(f"⏳ «{bag.bag_name}» — generation started in background.", "info")
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
# Necklaces (scarf-necklaces) — manual generation from storefront inspirations
# ---------------------------------------------------------------------------

@ai_content_bp.route("/necklaces")
@login_required
def necklaces():
    """Necklace gallery (generate new) + already-generated necklaces (regenerate)."""
    from .services.inspirations_client import list_inspirations
    items = list_inspirations(category="necklace")

    # Already-generated necklaces, newest first, each with its latest result.
    rows = (
        BagQueue.query.filter_by(product_type="necklace")
        .order_by(BagQueue.created_at.desc())
        .limit(24)
        .all()
    )
    generated = []
    for bag in rows:
        latest = (
            PendingApproval.query.filter_by(bag_queue_id=bag.id)
            .order_by(PendingApproval.created_at.desc())
            .first()
        )
        generated.append({"bag": bag, "approval": latest})

    return render_template(
        "ai_content/necklaces.html", items=items, generated=generated,
    )


def _start_async(fn) -> None:
    """Run fn(app) in a daemon thread with an app context (fire-and-forget)."""
    import threading
    from flask import current_app
    app = current_app._get_current_object()

    def _runner():
        with app.app_context():
            fn(app)

    threading.Thread(target=_runner, daemon=True).start()


@ai_content_bp.route("/necklaces/generate", methods=["POST"])
@login_required
def necklaces_generate():
    """One-click generate. On-neck photo is OPTIONAL (improves size accuracy);
    the prompt is the built-in necklace default — no manual prompt needed."""
    name = request.form.get("name", "").strip() or "Necklace"
    product_url = request.form.get("product_url", "").strip()
    custom_prompt = request.form.get("custom_prompt", "").strip() or None
    reference_url = request.form.get("reference_url", "").strip() or None
    file = request.files.get("neck_image")

    if not product_url:
        flash("პროდუქტის ფოტო ვერ მოიძებნა — სცადე გვერდის განახლება.", "danger")
        return redirect(url_for("ai_content.necklaces"))

    # On-neck photo is optional. When provided, upload it as the size reference.
    on_neck_url = None
    if file and file.filename:
        if not _allowed_file(file.filename):
            flash("მხოლოდ JPG, PNG ან WebP ფორმატია დაშვებული.", "danger")
            return redirect(url_for("ai_content.necklaces"))
        from .services.cloudinary_svc import upload_image
        suffix = pathlib.Path(secure_filename(file.filename)).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            file.save(tmp.name)
            result = upload_image(tmp.name, tenant_id="default", category="references")
        os.unlink(tmp.name)
        if not result["success"]:
            flash(f"„ყელზე“ ფოტო Cloudinary-ზე ვერ ავიდა: {result['error']}", "danger")
            return redirect(url_for("ai_content.necklaces"))
        on_neck_url = result["public_url"]

    bag = BagQueue(
        product_type="necklace",
        bag_name=name,
        image_path=product_url,
        image_path_open=on_neck_url,  # None = no size reference (one-click mode)
        custom_prompt=custom_prompt,
        reference_url=reference_url,
        status="pending",
        sort_order=0,
    )
    db.session.add(bag)
    db.session.commit()
    bag_id = bag.id

    def _run(_app):
        from .services.orchestrator import trigger_for_bag
        trigger_for_bag(bag_id)

    _start_async(_run)
    flash(f"⏳ «{name}» — გენერაცია დაიწყო. ფოტო Telegram-ში მოვა ~60 წამში.", "info")
    return redirect(url_for("ai_content.necklaces"))


@ai_content_bp.route("/necklaces/<int:bag_id>/regenerate", methods=["POST"])
@login_required
def necklaces_regenerate(bag_id: int):
    """Re-run a necklace WITHOUT re-uploading — reuses the saved product photo,
    on-neck photo, and prompt. New photo arrives in Telegram for approval."""
    bag = BagQueue.query.get_or_404(bag_id)
    if bag.product_type != "necklace":
        flash("ეს ჩანაწერი ყელსაბამი არ არის.", "warning")
        return redirect(url_for("ai_content.necklaces"))

    latest = (
        PendingApproval.query.filter_by(bag_queue_id=bag.id)
        .order_by(PendingApproval.created_at.desc())
        .first()
    )
    if latest is not None:
        approval_id = latest.id

        def _run(_app):
            from .services.orchestrator import regenerate_approval
            regenerate_approval(approval_id)

        _start_async(_run)
    else:
        # Never produced an approval (e.g. failed) — re-trigger the saved row.
        bag.status = "failed"
        db.session.commit()

        def _run(_app):
            from .services.orchestrator import trigger_for_bag
            trigger_for_bag(bag_id)

        _start_async(_run)

    flash(f"🔄 «{bag.bag_name}» — რეგენერაცია დაიწყო. ახალი ფოტო Telegram-ში მოვა.", "info")
    return redirect(url_for("ai_content.necklaces"))


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

@ai_content_bp.route("/approvals")
@login_required
def approvals():
    rows = (
        PendingApproval.query
        .order_by(PendingApproval.created_at.desc())
        .limit(200)
        .all()
    )
    grouped = {"pending": [], "approved": [], "posted": [], "rejected": []}
    for a in rows:
        grouped.setdefault(a.status, []).append(a)
    return render_template("ai_content/approvals.html", grouped=grouped)


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


@ai_content_bp.route("/approvals/<int:approval_id>/retry-fb", methods=["POST"])
@login_required
def approval_retry_fb(approval_id: int):
    """Retry only the Facebook half — used when IG already posted but FB failed."""
    from .services.social_poster import post_to_facebook_only
    result = post_to_facebook_only(approval_id)
    if result.get("success"):
        flash("✅ Facebook-ზე გამოქვეყნდა.", "success")
    else:
        flash(f"❌ FB: {result.get('error', 'unknown')}", "danger")
    return redirect(url_for("ai_content.approvals"))


@ai_content_bp.route("/approvals/<int:approval_id>/cancel", methods=["POST"])
@login_required
def approval_cancel(approval_id: int):
    """Undo an accidental approve — flips approved → rejected so 20:00 cron skips it."""
    from datetime import datetime, timezone
    approval = PendingApproval.query.get_or_404(approval_id)
    if approval.status not in ("approved", "pending"):
        flash(f"⚠️ Status='{approval.status}' — ცადო post-ი ვერ გავა.", "warning")
        return redirect(request.referrer or url_for("ai_content.dashboard"))
    approval.status = "rejected"
    approval.responded_at = datetime.now(timezone.utc)
    db.session.commit()
    flash(f"🛑 Approval #{approval_id} გაუქმდა — 20:00 cron-ი არ ცადებს.", "success")
    return redirect(request.referrer or url_for("ai_content.dashboard"))


@ai_content_bp.route("/approvals/<int:approval_id>/approve", methods=["POST"])
@login_required
def approval_approve(approval_id: int):
    """Approve from web — same effect as the ✅ button in Telegram."""
    from datetime import datetime, timezone
    approval = PendingApproval.query.get_or_404(approval_id)
    if approval.status != "pending":
        flash(f"⚠️ Status='{approval.status}' — მხოლოდ pending-ი შეიძლება დადასტურდეს.",
              "warning")
        return redirect(request.referrer or url_for("ai_content.dashboard"))
    approval.status = "approved"
    approval.responded_at = datetime.now(timezone.utc)
    db.session.commit()
    flash(f"✅ Approval #{approval_id} approved — 20:00 cron-ი ცადებს გავა.", "success")
    return redirect(request.referrer or url_for("ai_content.dashboard"))


@ai_content_bp.route("/approvals/<int:approval_id>/regenerate", methods=["POST"])
@login_required
def approval_regenerate(approval_id: int):
    """🔄 / 🎨 — re-run the pipeline (optionally with an extra prompt) in background."""
    import threading
    from flask import current_app

    approval = PendingApproval.query.get_or_404(approval_id)
    if approval.status not in ("pending", "rejected"):
        flash(f"⚠️ Status='{approval.status}' — regen only on pending/rejected.", "warning")
        return redirect(request.referrer or url_for("ai_content.dashboard"))
    max_regen = int(os.environ.get("MAX_REGENERATIONS", "3"))
    if approval.regeneration_count >= max_regen:
        flash(f"⚠️ Max regenerations ({max_regen}) reached for #{approval_id}.", "warning")
        return redirect(request.referrer or url_for("ai_content.dashboard"))

    extra_prompt = (request.form.get("extra_prompt", "") or "").strip()
    app = current_app._get_current_object()

    def _run_regen():
        with app.app_context():
            from .services.orchestrator import regenerate_approval
            regenerate_approval(approval_id, extra_prompt)

    threading.Thread(target=_run_regen, daemon=True).start()
    if extra_prompt:
        flash(
            f"🎨 Regenerating #{approval_id} with prompt: "
            f"«{extra_prompt[:60]}{'…' if len(extra_prompt) > 60 else ''}». "
            "ფოტო Telegram-ში მოვა 30-60s-ში.",
            "info",
        )
    else:
        flash(
            f"🔄 Regenerating #{approval_id} in background. "
            "ფოტო Telegram-ში მოვა 30-60s-ში.",
            "info",
        )
    return redirect(request.referrer or url_for("ai_content.dashboard"))


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

    from .services.social_poster import generate_caption
    fb_preview = approval.fb_caption or generate_caption(approval, platform="fb")
    ig_preview = approval.ig_caption or generate_caption(approval, platform="ig")
    fb_is_saved = bool(approval.fb_caption)
    ig_is_saved = bool(approval.ig_caption)
    return render_template(
        "ai_content/approval_edit.html",
        approval=approval,
        fb_preview=fb_preview,
        ig_preview=ig_preview,
        fb_is_saved=fb_is_saved,
        ig_is_saved=ig_is_saved,
    )


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
    ("STOREFRONT_API_KEY", "Storefront (bags)"),
    ("INSPIRATIONS_API_KEY", "Inspirations (necklaces)"),
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
    pinterest_status = _pinterest_oauth_status()
    try:
        from .services.scheduler import next_run_times
        next_runs = next_run_times()
    except Exception:
        next_runs = None
    return render_template(
        "ai_content/settings.html",
        values=values,
        credentials=credentials,
        pinterest_status=pinterest_status,
        next_runs=next_runs,
    )


def _pinterest_oauth_status() -> dict:
    """Return current Pinterest OAuth state for the Settings widget."""
    has_secret = bool(os.environ.get("PINTEREST_APP_SECRET"))
    redirect_uri = os.environ.get(
        "PINTEREST_REDIRECT_URI", "http://localhost:8080/oauth/callback",
    )
    refresh_token = Setting.get("pinterest_refresh_token", default="") or ""
    expires_raw = Setting.get("pinterest_token_expires_at", default="") or ""
    days_left = None
    if expires_raw:
        try:
            dt = datetime.fromisoformat(expires_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days_left = round((dt - datetime.now(timezone.utc)).total_seconds() / 86400, 1)
        except ValueError:
            pass
    return {
        "configured": has_secret,
        "redirect_uri": redirect_uri,
        "connected": bool(refresh_token),
        "expires_in_days": days_left,
    }


# ---------------------------------------------------------------------------
# Pinterest OAuth — one-time admin click → tokens auto-refresh from then on
# ---------------------------------------------------------------------------

@ai_content_bp.route("/pinterest/oauth/connect")
@login_required
def pinterest_oauth_connect():
    """Start the Pinterest OAuth flow — redirects the admin to Pinterest."""
    from .services.pinterest_oauth import get_authorization_url
    state = secrets.token_urlsafe(24)
    session["pinterest_oauth_state"] = state
    try:
        url = get_authorization_url(state=state)
    except RuntimeError as exc:
        flash(f"❌ Pinterest OAuth not configured: {exc}", "danger")
        return redirect(url_for("ai_content.settings_view"))
    return redirect(url)


@ai_content_bp.route("/pinterest/oauth/callback")
@login_required
def pinterest_oauth_callback():
    """Pinterest redirects here with ?code=... after admin clicks Allow."""
    from .services.pinterest_oauth import exchange_code_for_tokens

    error = request.args.get("error")
    if error:
        flash(f"❌ Pinterest denied access: {error}", "danger")
        return redirect(url_for("ai_content.settings_view"))

    code = request.args.get("code")
    state = request.args.get("state")
    expected = session.pop("pinterest_oauth_state", None)
    if not code or state != expected:
        flash("❌ Pinterest OAuth state mismatch — try Connect again.", "danger")
        return redirect(url_for("ai_content.settings_view"))

    result = exchange_code_for_tokens(code)
    if not result["success"]:
        flash(f"❌ Token exchange failed: {result['error']}", "danger")
        return redirect(url_for("ai_content.settings_view"))

    days = round(result["expires_in"] / 86400)
    flash(f"✅ Pinterest connected — access token valid for ~{days} days, "
          "refresh token saved (auto-renews going forward).", "success")
    return redirect(url_for("ai_content.settings_view"))


# ---------------------------------------------------------------------------
# Manual job triggers (synchronous — admin sees result after pipeline finishes)
# ---------------------------------------------------------------------------

@ai_content_bp.route("/jobs/run-generate", methods=["POST"])
@login_required
def jobs_run_generate():
    """Fire-and-forget: pipeline runs in a daemon thread so Railway's
    ~75 s HTTP edge timeout doesn't kill the request. Admin watches
    progress on the queue/approvals page (which auto-refreshes)."""
    import threading
    from flask import current_app
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            from .services.orchestrator import run_generate_job
            run_generate_job()

    threading.Thread(target=_run, daemon=True).start()
    flash(
        "⏳ Generate job started in background. ფოტო Telegram-ში მოვა 60–180 წამში.",
        "info",
    )
    return redirect(url_for("ai_content.dashboard"))


@ai_content_bp.route("/jobs/run-post", methods=["POST"])
@login_required
def jobs_run_post():
    """Fire-and-forget — same reason as run-generate."""
    import threading
    from flask import current_app
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            from .services.orchestrator import run_post_job
            run_post_job()

    threading.Thread(target=_run, daemon=True).start()
    flash(
        "⏳ Post job started in background. ყველა approved approval გავა FB + IG-ზე.",
        "info",
    )
    return redirect(url_for("ai_content.dashboard"))
