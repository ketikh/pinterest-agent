"""Admin panel routes — Stage 0 skeleton (dashboard only)."""

from flask import render_template
from flask_login import login_required

from . import ai_content_bp
from .models import BagQueue, PendingApproval, PostLog


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
