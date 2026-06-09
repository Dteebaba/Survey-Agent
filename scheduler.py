"""
scheduler.py
============
Robust singleton background scheduler using APScheduler.
Runs the autonomous pipeline daily at 9 PM ET (01:00 UTC).

Safe to import and call start_scheduler() on every server startup or
Streamlit rerun — it will only ever create ONE scheduler thread.

Replit deployment notes
-----------------------
- Enable "Always-On" (Replit Core / Hacker plan) so the process stays
  alive overnight.  Without it the scheduler only fires while a browser
  tab is open.
- If you move to a Replit Deployment (Autoscale/Reserved VM), the
  process is always alive — no extra configuration needed.
"""

import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Singleton guards ──────────────────────────────────────────────────────────
_scheduler = None          # APScheduler instance
_lock      = threading.Lock()
_last_run_result: Optional[dict] = None   # stores outcome of most-recent job run


# ── Job ───────────────────────────────────────────────────────────────────────

def _job_run_pipeline():
    """Executed by the scheduler at the scheduled time."""
    global _last_run_result

    started = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info("=" * 60)
    logger.info("🔄 SCHEDULED PIPELINE STARTED  %s", started)
    logger.info("=" * 60)

    result = {
        "started_at": started,
        "finished_at": None,
        "rows_added": 0,
        "message": "",
        "errors": [],
    }

    try:
        from autonomous_agent import run_pipeline
        summary = run_pipeline()

        result["rows_added"] = summary.get("total_rows_added", 0)
        result["message"]    = summary.get("message", "")
        result["errors"]     = summary.get("errors", [])

        for err in result["errors"]:
            logger.error("  ❌ %s", err)

        logger.info("✅ Pipeline done | rows=%s | %s",
                    result["rows_added"], result["message"])

    except Exception as exc:
        msg = f"Unhandled exception: {exc}"
        logger.error(msg, exc_info=True)
        result["errors"].append(msg)
        result["message"] = msg
        try:
            from agent_state import add_error
            add_error(msg)
        except Exception:
            pass

    result["finished_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    _last_run_result = result
    logger.info("=" * 60)


# ── Public API ────────────────────────────────────────────────────────────────

def start_scheduler():
    """
    Start the background scheduler (idempotent).
    Job: daily at 01:00 UTC = 9 PM ET (EDT).
    For EST (winter, Nov–Mar) add a second job at 02:00 UTC if needed.
    """
    global _scheduler

    with _lock:
        if _scheduler is not None and _scheduler.running:
            logger.debug("Scheduler already running — skipping init")
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger

            _scheduler = BackgroundScheduler(daemon=True)

            _scheduler.add_job(
                _job_run_pipeline,
                CronTrigger(hour=1, minute=0, timezone="UTC"),  # 9 PM ET
                id="daily_pipeline",
                name="Daily Autonomous Opportunity Pipeline",
                replace_existing=True,
                misfire_grace_time=3600,   # run even if up to 1 h late
                coalesce=True,             # if multiple missed firings, run once
            )

            _scheduler.start()

            jobs     = _scheduler.get_jobs()
            next_run = jobs[0].next_run_time if jobs else "unknown"
            logger.info("✅ Scheduler started | next run: %s", next_run)

        except Exception as exc:
            logger.error("❌ Scheduler failed to start: %s", exc, exc_info=True)
            _scheduler = None
            raise


def stop_scheduler():
    """Gracefully shut down the scheduler (call on app teardown)."""
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return a status dict for the admin/autonomous-agent UI panel."""
    global _scheduler, _last_run_result

    if _scheduler is None or not _scheduler.running:
        return {
            "running": False,
            "message": "Scheduler not running",
            "last_run": _last_run_result,
        }

    jobs = _scheduler.get_jobs()
    return {
        "running":  True,
        "job_name": jobs[0].name if jobs else "—",
        "next_run": str(jobs[0].next_run_time) if jobs else "—",
        "trigger":  str(jobs[0].trigger) if jobs else "—",
        "last_run": _last_run_result,
    }


def force_run_now() -> dict:
    """Manually trigger the pipeline right now (for testing)."""
    logger.info("🔄 Force-running pipeline immediately…")
    _job_run_pipeline()
    return _last_run_result or {"status": "ran"}