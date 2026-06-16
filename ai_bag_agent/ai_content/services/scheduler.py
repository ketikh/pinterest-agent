"""APScheduler glue — registers the daily generate + post jobs.

Architecture:
    BackgroundScheduler (sync) runs in the Flask process. Each job pushes
    its own Flask app context before touching the DB. The scheduler is
    only started inside the worker that actually serves requests — under
    Flask's debug reloader we'd otherwise spawn two parallel schedulers.

Schedule defaults (overridable via .env):
    MORNING_JOB_HOUR / MORNING_JOB_MINUTE → run_generate_job()
    EVENING_JOB_HOUR / EVENING_JOB_MINUTE → run_post_job()
    SCHEDULER_TIMEZONE                    → Asia/Tbilisi
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _parse_time(hour_env: str, minute_env: str, default_hour: int,
                default_minute: int) -> tuple:
    """Read an hour/minute from env, tolerating "HH", "HH:MM", and bad values.

    Operators naturally type a full time like "22:00" into an hour variable;
    a bare int() on that raised ValueError and crashed the whole scheduler.
    """
    raw_hour = (os.environ.get(hour_env, "") or "").strip()
    raw_minute = (os.environ.get(minute_env, "") or "").strip()

    hour, minute = default_hour, default_minute
    if ":" in raw_hour:  # e.g. "22:00" or "22:30" in the hour var
        h_part, _, m_part = raw_hour.partition(":")
        try:
            hour = int(h_part.strip())
            minute = int(m_part.strip()) if m_part.strip() else default_minute
        except ValueError:
            hour, minute = default_hour, default_minute
        return hour, minute

    if raw_hour:
        try:
            hour = int(raw_hour)
        except ValueError:
            hour = default_hour
    if raw_minute:
        try:
            minute = int(raw_minute)
        except ValueError:
            minute = default_minute
    return hour, minute


def init_scheduler(flask_app) -> Optional[BackgroundScheduler]:
    """Start the BackgroundScheduler in the current process.

    Returns None when skipped (testing, reloader parent process, or already
    running). Returns the started scheduler instance otherwise.
    """
    global _scheduler

    if flask_app.config.get("TESTING"):
        logger.debug("Scheduler: skipped (TESTING)")
        return None

    # Flask's debug auto-reloader spawns a parent monitor and a child worker.
    # We only want the scheduler in the child to avoid double-firing jobs.
    if (
        flask_app.config.get("DEBUG")
        and os.environ.get("WERKZEUG_RUN_MAIN") != "true"
    ):
        logger.debug("Scheduler: skipped (Werkzeug reloader parent process)")
        return None

    if _scheduler is not None and _scheduler.running:
        logger.debug("Scheduler: already running")
        return _scheduler

    timezone = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Tbilisi")
    morning_hour, morning_minute = _parse_time(
        "MORNING_JOB_HOUR", "MORNING_JOB_MINUTE", 12, 0)
    evening_hour, evening_minute = _parse_time(
        "EVENING_JOB_HOUR", "EVENING_JOB_MINUTE", 20, 0)
    # Necklaces post later than bags (default 22:00) so each product type gets
    # its own slot in the daily feed.
    necklace_post_hour, necklace_post_minute = _parse_time(
        "NECKLACE_POST_HOUR", "NECKLACE_POST_MINUTE", 22, 0)

    scheduler = BackgroundScheduler(timezone=timezone)

    # Morning: generate one bag AND one necklace → Telegram for approval.
    scheduler.add_job(
        func=_run_morning_in_context,
        trigger=CronTrigger(hour=morning_hour, minute=morning_minute, timezone=timezone),
        args=[flask_app],
        id="morning_generate",
        name="Daily generate job (bag + necklace)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Evening: post approved BAGS.
    scheduler.add_job(
        func=_run_evening_in_context,
        trigger=CronTrigger(hour=evening_hour, minute=evening_minute, timezone=timezone),
        args=[flask_app],
        id="evening_post",
        name="Daily bag post job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Later evening: post approved NECKLACES.
    scheduler.add_job(
        func=_run_necklace_post_in_context,
        trigger=CronTrigger(
            hour=necklace_post_hour, minute=necklace_post_minute, timezone=timezone
        ),
        args=[flask_app],
        id="necklace_post",
        name="Daily necklace post job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started — generate at %02d:%02d, bag-post at %02d:%02d, "
        "necklace-post at %02d:%02d (%s)",
        morning_hour, morning_minute, evening_hour, evening_minute,
        necklace_post_hour, necklace_post_minute, timezone,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def get_scheduler() -> Optional[BackgroundScheduler]:
    return _scheduler


def next_run_times() -> dict:
    """Return next-run timestamps for the dashboard widget."""
    if _scheduler is None or not _scheduler.running:
        return {"morning": None, "evening": None}
    jobs = {j.id: j.next_run_time for j in _scheduler.get_jobs()}
    return {
        "morning": jobs.get("morning_generate"),
        "evening": jobs.get("evening_post"),
        "necklace_post": jobs.get("necklace_post"),
    }


# ---------------------------------------------------------------------------
# Job wrappers — each pushes a Flask app context before touching the DB
# ---------------------------------------------------------------------------

def _run_morning_in_context(flask_app) -> None:
    """Generate one bag AND one necklace. Each is isolated so one failing
    doesn't stop the other."""
    with flask_app.app_context():
        from .orchestrator import run_generate_job, run_necklace_generate_job
        try:
            result = run_generate_job(tenant_id="default")
            logger.info("Morning bag job: %s", result)
        except Exception:
            logger.exception("Morning bag job crashed")
        try:
            result = run_necklace_generate_job(tenant_id="default")
            logger.info("Morning necklace job: %s", result)
        except Exception:
            logger.exception("Morning necklace job crashed")


def _run_evening_in_context(flask_app) -> None:
    """Post approved BAGS (necklaces post later — see _run_necklace_post)."""
    with flask_app.app_context():
        from .orchestrator import run_post_job
        try:
            result = run_post_job(tenant_id="default", product_type="bag")
            logger.info("Evening bag post job: %s", result)
        except Exception:
            logger.exception("Evening bag post job crashed")


def _run_necklace_post_in_context(flask_app) -> None:
    """Post approved NECKLACES (runs later than the bag post job)."""
    with flask_app.app_context():
        from .orchestrator import run_post_job
        try:
            result = run_post_job(tenant_id="default", product_type="necklace")
            logger.info("Necklace post job: %s", result)
        except Exception:
            logger.exception("Necklace post job crashed")
