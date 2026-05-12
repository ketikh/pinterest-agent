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
    morning_hour = int(os.environ.get("MORNING_JOB_HOUR", "12"))
    morning_minute = int(os.environ.get("MORNING_JOB_MINUTE", "0"))
    evening_hour = int(os.environ.get("EVENING_JOB_HOUR", "20"))
    evening_minute = int(os.environ.get("EVENING_JOB_MINUTE", "0"))

    scheduler = BackgroundScheduler(timezone=timezone)

    scheduler.add_job(
        func=_run_morning_in_context,
        trigger=CronTrigger(hour=morning_hour, minute=morning_minute, timezone=timezone),
        args=[flask_app],
        id="morning_generate",
        name="Daily generate job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        func=_run_evening_in_context,
        trigger=CronTrigger(hour=evening_hour, minute=evening_minute, timezone=timezone),
        args=[flask_app],
        id="evening_post",
        name="Daily post job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started — generate at %02d:%02d, post at %02d:%02d (%s)",
        morning_hour, morning_minute, evening_hour, evening_minute, timezone,
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
    }


# ---------------------------------------------------------------------------
# Job wrappers — each pushes a Flask app context before touching the DB
# ---------------------------------------------------------------------------

def _run_morning_in_context(flask_app) -> None:
    with flask_app.app_context():
        from .orchestrator import run_generate_job
        try:
            result = run_generate_job(tenant_id="default")
            logger.info("Morning job: %s", result)
        except Exception:
            logger.exception("Morning job crashed")


def _run_evening_in_context(flask_app) -> None:
    with flask_app.app_context():
        from .orchestrator import run_post_job
        try:
            result = run_post_job(tenant_id="default")
            logger.info("Evening job: %s", result)
        except Exception:
            logger.exception("Evening job crashed")
