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

    # Jinja filter: render UTC datetimes in the configured local timezone
    _register_time_filters(app)

    # Configure logging
    _configure_logging(app)

    # Telegram bot — runs in a background thread (skip during tests)
    if not app.config.get("TESTING") and os.environ.get("TELEGRAM_BOT_TOKEN"):
        from .ai_content.services.telegram_bot import init_telegram_bot
        init_telegram_bot(app)

    # APScheduler — daily generate (12:00) + post (20:00) jobs
    if not app.config.get("TESTING"):
        from .ai_content.services.scheduler import init_scheduler
        init_scheduler(app)

    return app


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
    from datetime import datetime, timezone
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
