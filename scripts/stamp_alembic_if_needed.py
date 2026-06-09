"""One-off recovery: stamp alembic_version on a DB created via db.create_all().

Some early Railway deploys created the schema via `db.create_all()` before
Flask-Migrate was wired in. As a result there is no `alembic_version` table
on production Postgres, and every `flask db upgrade` tries to re-apply the
initial migration → DuplicateTable error → later migrations never run, so
columns added afterwards (image_path_open, fb_caption, …) are missing.

This script runs BEFORE `flask db upgrade` on every deploy. It inspects the
live schema, decides which Alembic revision the DB matches, and writes that
revision into `alembic_version` so the subsequent `db upgrade` only applies
the migrations the DB is actually missing. Idempotent — does nothing once
`alembic_version` exists.
"""

from __future__ import annotations

import logging
import os
import sys

from sqlalchemy import create_engine, inspect, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] stamp: %(message)s",
)
log = logging.getLogger("stamp_alembic")


# Map "what columns are present" → "which migration was the last applied".
# Order matters — first match wins. Check newest-first so we stamp the
# highest revision the DB could possibly be at.
def _detect_revision(insp) -> str:
    existing = set(insp.get_table_names())
    bag = {c["name"] for c in insp.get_columns("bag_queue")} if "bag_queue" in existing else set()
    pa = {c["name"] for c in insp.get_columns("pending_approvals")} if "pending_approvals" in existing else set()
    pl = {c["name"] for c in insp.get_columns("post_log")} if "post_log" in existing else set()

    if "image_path_open" in bag:
        return "a8c1d2e3f4b5"
    if "fb_caption" in pa:
        return "f54ccc0c063d"
    if "fb_status" in pl:
        return "79ea06351249"
    if "reference_url" in bag:
        return "e1c1c6ebf70c"
    return "e1bd2f069b06"  # initial


def main() -> int:
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("SQLALCHEMY_DATABASE_URI")
    if not db_url:
        log.info("No DATABASE_URL set — assuming fresh local DB, skipping stamp")
        return 0

    # Railway pre-2024 connection strings sometimes still use `postgres://`
    # which SQLAlchemy 2.x refuses; rewrite to the modern scheme.
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
    except Exception as exc:
        log.error("Could not create engine: %s", exc)
        return 1

    try:
        insp = inspect(engine)
        existing = set(insp.get_table_names())
    except Exception as exc:
        log.warning("Could not inspect DB (%s) — letting db upgrade try anyway", exc)
        return 0

    if "alembic_version" in existing:
        try:
            with engine.connect() as conn:
                rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            log.info("alembic_version already present (revision=%s) — no stamp needed", rev)
        except Exception:
            log.info("alembic_version already present — no stamp needed")
        return 0

    if "bag_queue" not in existing:
        log.info("Fresh DB — db upgrade will create the schema, no stamp needed")
        return 0

    revision = _detect_revision(insp)
    log.info("Schema inspection → stamping alembic_version=%s", revision)

    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            ))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": revision},
            )
        log.info("Stamp successful — db upgrade will now apply only missing migrations")
        return 0
    except Exception as exc:
        log.error("Stamp failed: %s — db upgrade will likely also fail, surface this", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
