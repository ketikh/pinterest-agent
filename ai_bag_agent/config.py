"""Application configuration — loaded from environment variables."""

import os
from typing import Optional


class Config:
    """Base configuration shared by all environments."""

    SECRET_KEY: str = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-prod")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    MAX_CONTENT_LENGTH: int = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "10")) * 1024 * 1024

    # Scheduler
    SCHEDULER_TIMEZONE: str = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Tbilisi")
    MORNING_JOB_HOUR: int = int(os.environ.get("MORNING_JOB_HOUR", "9"))
    MORNING_JOB_MINUTE: int = int(os.environ.get("MORNING_JOB_MINUTE", "0"))
    EVENING_JOB_HOUR: int = int(os.environ.get("EVENING_JOB_HOUR", "20"))
    EVENING_JOB_MINUTE: int = int(os.environ.get("EVENING_JOB_MINUTE", "0"))

    # Business logic
    MAX_REGENERATIONS: int = int(os.environ.get("MAX_REGENERATIONS", "3"))
    RECENT_PIN_CACHE_DAYS: int = int(os.environ.get("RECENT_PIN_CACHE_DAYS", "7"))
    DEFAULT_TENANT_ID: str = "default"

    # Pinterest
    PINTEREST_APP_ID: Optional[str] = os.environ.get("PINTEREST_APP_ID")
    PINTEREST_ACCESS_TOKEN: Optional[str] = os.environ.get("PINTEREST_ACCESS_TOKEN")
    PINTEREST_BOARD_ID: Optional[str] = os.environ.get("PINTEREST_BOARD_ID")

    # kie.ai
    KIEAI_API_KEY: Optional[str] = os.environ.get("KIEAI_API_KEY")
    KIEAI_MODEL: str = os.environ.get("KIEAI_MODEL", "nano-banana-pro")

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: Optional[str] = os.environ.get("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY: Optional[str] = os.environ.get("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET: Optional[str] = os.environ.get("CLOUDINARY_API_SECRET")

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = os.environ.get("TELEGRAM_CHAT_ID")
    TELEGRAM_WEBHOOK_URL: Optional[str] = os.environ.get("TELEGRAM_WEBHOOK_URL")

    # Anthropic (Claude) — AI caption generation
    ANTHROPIC_API_KEY: Optional[str] = os.environ.get("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    # Meta (Facebook + Instagram)
    FB_PAGE_TOKEN: Optional[str] = os.environ.get("FB_PAGE_TOKEN")
    FB_PAGE_ID: Optional[str] = os.environ.get("FB_PAGE_ID")
    IG_BUSINESS_ACCOUNT_ID: Optional[str] = os.environ.get("IG_BUSINESS_ACCOUNT_ID")
    META_API_VERSION: str = os.environ.get("META_API_VERSION", "v21.0")
    META_GRAPH_BASE: str = f"https://graph.facebook.com/{os.environ.get('META_API_VERSION', 'v21.0')}"


def _normalize_db_url(url: str) -> str:
    """Railway / Heroku still hand out the legacy `postgres://` scheme but
    SQLAlchemy 2.x only accepts `postgresql://`. Rewrite it transparently."""
    if url and url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _dev_db_uri() -> str:
    """Compute absolute SQLite URI for development."""
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return _normalize_db_url(env_url)
    base = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    instance_dir = os.path.join(base, "instance")
    os.makedirs(instance_dir, exist_ok=True)
    return f"sqlite:///{os.path.join(instance_dir, 'pinterest_agent.db')}"


class DevelopmentConfig(Config):
    DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = False
    SQLALCHEMY_DATABASE_URI: str = _dev_db_uri()


class TestingConfig(Config):
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    WTF_CSRF_ENABLED: bool = False
    SECRET_KEY: str = "test-secret-key"


def _prod_db_uri() -> str:
    """Production DB URL — Postgres from Railway, or a SQLite fallback in /tmp.

    Relying on a writable `instance/` folder inside the container is fragile
    (Nixpacks builds to /app which is read-only on some setups). When Railway
    has no DATABASE_URL we fall back to /tmp so the app at least boots; admin
    is expected to add a PostgreSQL plugin for real persistence.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return _normalize_db_url(url)
    fallback_dir = "/tmp/pinterest-agent-data"
    os.makedirs(fallback_dir, exist_ok=True)
    return f"sqlite:///{fallback_dir}/pinterest_agent.db"


class ProductionConfig(Config):
    DEBUG: bool = False
    SQLALCHEMY_DATABASE_URI: str = _prod_db_uri()


_configs = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config() -> "type[Config]":
    env = os.environ.get("FLASK_ENV", "development")
    return _configs.get(env, DevelopmentConfig)
