"""ai_content Blueprint — the main feature module (migration-ready unit)."""

from flask import Blueprint

ai_content_bp = Blueprint(
    "ai_content",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
