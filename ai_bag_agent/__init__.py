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

    # Register blueprints
    from .auth import auth_bp
    from .ai_content import ai_content_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(ai_content_bp)

    # Health check (no auth required)
    @app.route("/health")
    def health():
        return {"status": "ok", "service": "pinterest-agent"}

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


def _configure_logging(app: Flask) -> None:
    if app.config.get("TESTING"):
        return

    level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
