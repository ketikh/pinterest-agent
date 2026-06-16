"""Flask application factory."""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional

from flask import Flask

from .config import get_config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_override: Optional[Dict] = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)

    # Load config
    app.config.from_object(get_config())
    if config_override:
        app.config.update(config_override)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Cross-origin iframe support (tissu-agent /admin/pinterest embeds us)
    _configure_iframe_embedding(app)

    # Register blueprints
    from .auth import auth_bp
    from .ai_content import ai_content_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(ai_content_bp)

    # Health check (no auth required)
    @app.route("/health")
    def health():
        return {"status": "ok", "service": "pinterest-agent"}

    @app.route("/health/db")
    def health_db():
        """Surface DB schema state so we can confirm migrations applied.

        No auth: returns table column names + alembic revision + tail of
        the deploy migration log. Safe — exposes no secrets, just schema.
        """
        import json as _json
        from pathlib import Path
        from sqlalchemy import inspect, text

        info: dict = {"service": "pinterest-agent"}
        try:
            url = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            info["db_driver"] = url.split(":", 1)[0] if url else "?"
        except Exception as exc:
            info["db_driver_error"] = str(exc)

        try:
            with app.app_context():
                insp = inspect(db.engine)
                info["tables"] = sorted(insp.get_table_names())
                for tbl in ("bag_queue", "pending_approvals"):
                    if tbl in info["tables"]:
                        info[f"{tbl}_columns"] = [c["name"] for c in insp.get_columns(tbl)]
                # Alembic current head
                try:
                    with db.engine.connect() as conn:
                        rev = conn.execute(text(
                            "SELECT version_num FROM alembic_version"
                        )).scalar()
                    info["alembic_version"] = rev
                except Exception as exc:
                    info["alembic_version_error"] = str(exc)
        except Exception as exc:
            info["schema_error"] = str(exc)

        # In-memory ring buffer of pipeline trace events (doesn't depend
        # on /tmp filesystem semantics).
        try:
            from .ai_content.services.orchestrator import get_recent_trace
            info["recent_trace"] = get_recent_trace()
        except Exception as exc:
            info["recent_trace_error"] = str(exc)

        # Tail of the stamp + migrate logs written by railway.toml startCommand
        for log_name in ("stamp.log", "migrate.log", "pipeline-errors.log", "pipeline.log"):
            log_path = Path(f"/tmp/{log_name}")
            key = log_name.replace(".log", "_log_tail").replace("-", "_")
            if log_path.exists():
                try:
                    lines = log_path.read_text(errors="replace").splitlines()
                    info[key] = lines[-40:]
                except Exception as exc:
                    info[key + "_error"] = str(exc)
            else:
                info[key] = "not-found"

        # Safe diagnostics — approval/post state so we can see why something
        # didn't post, without exposing the admin panel. No secrets.
        try:
            from sqlalchemy import func
            from .ai_content.models import BagQueue, PendingApproval, PostLog
            with app.app_context():
                rows = (
                    db.session.query(
                        BagQueue.product_type, PendingApproval.status, func.count()
                    )
                    .join(PendingApproval,
                          PendingApproval.bag_queue_id == BagQueue.id)
                    .group_by(BagQueue.product_type, PendingApproval.status)
                    .all()
                )
                info["approvals"] = [
                    {"type": r[0], "status": r[1], "count": r[2]} for r in rows
                ]
                posts = (
                    PostLog.query.order_by(PostLog.posted_at.desc()).limit(8).all()
                )
                info["recent_posts"] = [
                    {
                        "approval_id": p.approval_id,
                        "fb": p.fb_status, "ig": p.ig_status,
                        "fb_error": (p.fb_error or "")[:200],
                        "ig_error": (p.ig_error or "")[:200],
                        "at": p.posted_at.isoformat() if p.posted_at else None,
                    }
                    for p in posts
                ]
        except Exception as exc:
            info["diag_error"] = str(exc)

        # Redact any secrets that may have leaked into log tails / error
        # strings (e.g. the Telegram token in an httpx request URL).
        def _redact(blob: str) -> str:
            import re
            secrets = []
            for k, v in os.environ.items():
                if not v or len(v) < 8:
                    continue
                if any(t in k.upper() for t in
                       ("TOKEN", "KEY", "SECRET", "PASSWORD", "DATABASE_URL")):
                    secrets.append(v)
            for v in sorted(set(secrets), key=len, reverse=True):
                blob = blob.replace(v, "***")
            blob = re.sub(r"bot\d+:[A-Za-z0-9_-]{20,}", "bot***", blob)
            blob = re.sub(r"ghp_[A-Za-z0-9]{20,}", "ghp_***", blob)
            blob = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]{10,}", r"\1***", blob)
            blob = re.sub(
                r"(?i)([?&](?:token|key|api_key|secret|password)=)[^&\s\"']+",
                r"\1***", blob,
            )
            return blob

        payload = _redact(_json.dumps(info, indent=2, ensure_ascii=False))
        return payload, 200, {
            "Content-Type": "application/json; charset=utf-8",
        }

    # Jinja filter: render UTC datetimes in the configured local timezone
    _register_time_filters(app)

    # Configure logging
    _configure_logging(app)

    # Telegram bot — runs in a background thread (skip during tests).
    # Wrapped in try/except so a startup failure here (network, bad token,
    # …) doesn't take down gunicorn before /health is reachable.
    if not app.config.get("TESTING") and os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            from .ai_content.services.telegram_bot import init_telegram_bot
            init_telegram_bot(app)
        except Exception:
            logging.getLogger(__name__).exception(
                "Telegram bot failed to initialise — continuing without it",
            )

    # APScheduler — daily generate (12:00) + post (20:00) jobs
    if not app.config.get("TESTING"):
        try:
            from .ai_content.services.scheduler import init_scheduler
            init_scheduler(app)
        except Exception:
            logging.getLogger(__name__).exception(
                "Scheduler failed to initialise — continuing without it",
            )

    # Bootstrap the first admin if ADMIN_USERNAME / ADMIN_PASSWORD are set
    # and the users table is empty. Idempotent.
    if not app.config.get("TESTING"):
        try:
            _bootstrap_admin(app)
        except Exception:
            logging.getLogger(__name__).exception(
                "Admin bootstrap skipped",
            )

    return app


def _bootstrap_admin(app: Flask) -> None:
    """Ensure an admin user exists matching the ADMIN_USERNAME / ADMIN_PASSWORD
    env vars. Runs on every boot — if the password env var was rotated, the
    DB row is updated to match. This is the recovery hatch when the operator
    forgets the password they set in Railway: they simply set a new
    ADMIN_PASSWORD in Variables and the next deploy re-syncs it.
    """
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not username or not password:
        return
    logger = logging.getLogger(__name__)
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            logger.exception("db.create_all() failed in bootstrap")
            return
        from .ai_content.models import User
        existing = User.query.filter_by(username=username).first()
        if existing is None:
            user = User(username=username, role="admin")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            logger.info("Bootstrapped admin user '%s'", username)
        else:
            # Sync password from env so the operator can recover access by
            # rotating ADMIN_PASSWORD in Railway Variables.
            if not existing.check_password(password):
                existing.set_password(password)
                db.session.commit()
                logger.info("Re-synced admin '%s' password from env", username)


def _configure_iframe_embedding(app: Flask) -> None:
    """Let the tissu-agent admin embed our admin in an <iframe>.

    Two things have to be right for the iframe to work cross-origin:

    1. CSP `frame-ancestors` must allow the parent's domain (and we must
       NOT send `X-Frame-Options: DENY`, which Flask doesn't by default).
    2. Session cookies must have `SameSite=None; Secure` so the browser
       sends them when the page is loaded inside the parent's frame.
       Without this the admin's login session is invisible in the iframe.

    Parent origins are configured via env (comma-separated):
        IFRAME_PARENT_ORIGINS=https://tissu-agent-production.up.railway.app
    """
    parents_raw = os.environ.get(
        "IFRAME_PARENT_ORIGINS",
        "https://tissu-agent-production.up.railway.app",
    )
    parent_origins = [o.strip() for o in parents_raw.split(",") if o.strip()]
    frame_ancestors = " ".join(["'self'"] + parent_origins)

    # Cross-origin iframe cookies need SameSite=None + Secure. Only flip in
    # production — local dev over http:// can't send Secure cookies.
    if not app.config.get("DEBUG") and not app.config.get("TESTING"):
        app.config.setdefault("SESSION_COOKIE_SAMESITE", "None")
        app.config.setdefault("SESSION_COOKIE_SECURE", True)
        app.config.setdefault("REMEMBER_COOKIE_SAMESITE", "None")
        app.config.setdefault("REMEMBER_COOKIE_SECURE", True)

    @app.after_request
    def _set_iframe_headers(response):
        # Drop any X-Frame-Options that Flask middleware or proxies may add;
        # CSP frame-ancestors is the modern, granular replacement.
        response.headers.pop("X-Frame-Options", None)
        existing_csp = response.headers.get("Content-Security-Policy", "")
        if "frame-ancestors" not in existing_csp:
            sep = "; " if existing_csp else ""
            response.headers["Content-Security-Policy"] = (
                f"{existing_csp}{sep}frame-ancestors {frame_ancestors}"
            )
        return response


def _register_time_filters(app: Flask) -> None:
    """`{{ dt | local_dt }}` converts UTC datetimes to SCHEDULER_TIMEZONE."""
    from datetime import timezone
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover — Python < 3.9
        from backports.zoneinfo import ZoneInfo

    tz_name = app.config.get("SCHEDULER_TIMEZONE") or "Asia/Tbilisi"

    def local_dt(dt, fmt: str = "%Y-%m-%d %H:%M") -> str:
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz_name)).strftime(fmt)

    app.jinja_env.filters["local_dt"] = local_dt


def _configure_logging(app: Flask) -> None:
    if app.config.get("TESTING"):
        return

    level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
