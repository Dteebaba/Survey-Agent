"""
scheduler.py
============
Singleton background scheduler using APScheduler.
Fires the autonomous pipeline daily at 10 PM America/New_York (handles
EDT ↔ EST automatically).

IMPORTANT — Replit deployment requirement
------------------------------------------
The scheduler runs in a background thread inside the same process as the
Streamlit app.  If the process sleeps (free Replit plan with no browser tab
open), the scheduler cannot fire.

To guarantee automatic nightly runs you MUST enable one of:
  • Replit "Always On"   (Core / Hacker plan)
  • Replit Deployment    (Autoscale or Reserved VM — process never sleeps)

Every run result — whether triggered by the scheduler or a user — is written
to agent_state.json so the dashboard always has a full history even after
a server restart.
"""

import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Singleton guards ──────────────────────────────────────────────────────────
_scheduler                = None
_lock                     = threading.Lock()
_last_run_result: Optional[dict] = None   # in-memory mirror (fallback)


# ── Job ───────────────────────────────────────────────────────────────────────

def _job_run_pipeline():
    """Executed automatically by the scheduler at 10 PM ET every night."""
    global _last_run_result

    started = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info("=" * 60)
    logger.info("🔄 SCHEDULED PIPELINE STARTED  %s", started)
    logger.info("=" * 60)

    result = {
        "started_at":  started,
        "finished_at": None,
        "rows_added":  0,
        "message":     "",
        "errors":      [],
    }

    summary = {
        "files_checked":    0,
        "files_processed":  0,
        "total_rows_added": 0,
        "errors":           [],
        "processed_files":  [],
        "message":          "",
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
        summary["errors"].append(msg)
        summary["message"] = msg
        try:
            from agent_state import add_error
            add_error(msg)
        except Exception:
            pass

    result["finished_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    _last_run_result = result

    # ── Persist to disk so dashboard survives restarts ─────────────────────
    try:
        from agent_state import record_run
        record_run("scheduled", summary)
        logger.info("✅ Run recorded to agent_state.json")
    except Exception as rec_err:
        logger.warning("Could not persist run record: %s", rec_err)

    logger.info("=" * 60)


# ── Public API ────────────────────────────────────────────────────────────────

def start_scheduler():
    """
    Start the background scheduler (idempotent — safe to call on every rerun).
    Job: daily at 22:00 America/New_York (10 PM ET, auto-adjusts EDT ↔ EST).
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
                CronTrigger(hour=22, minute=0, timezone="America/New_York"),
                id="daily_pipeline",
                name="Daily Autonomous Opportunity Pipeline — 10 PM ET",
                replace_existing=True,
                misfire_grace_time=3600,   # fire even if up to 1 h late
                coalesce=True,             # if multiple misfires, run once
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
    """Gracefully shut down the scheduler."""
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return a status dict for the dashboard panel."""
    global _scheduler, _last_run_result

    if _scheduler is None or not _scheduler.running:
        return {
            "running":  False,
            "message":  "Scheduler not running (process may have restarted)",
            "next_run": "—",
            "last_run": _last_run_result,
        }

    jobs = _scheduler.get_jobs()
    next_run_raw = jobs[0].next_run_time if jobs else None

    # Format next run time in ET
    next_run_str = "—"
    if next_run_raw:
        try:
            from datetime import timezone as tz
            import pytz
            et = pytz.timezone("America/New_York")
            next_run_et = next_run_raw.astimezone(et)
            next_run_str = next_run_et.strftime("%Y-%m-%d %I:%M %p ET")
        except Exception:
            next_run_str = str(next_run_raw)

    return {
        "running":  True,
        "job_name": jobs[0].name if jobs else "—",
        "next_run": next_run_str,
        "trigger":  str(jobs[0].trigger) if jobs else "—",
        "last_run": _last_run_result,
    }


def force_run_now() -> dict:
    """Manually trigger the pipeline right now (for testing/admin use)."""
    logger.info("🔄 Force-running pipeline immediately…")
    _job_run_pipeline()
    return _last_run_result or {}
