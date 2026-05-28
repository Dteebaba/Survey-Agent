"""
Background Scheduler using APScheduler.
Runs autonomous pipeline daily at 10 PM ET.

On Replit, enable "Always-On" mode to keep scheduler running 24/7.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import threading

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = None
_scheduler_lock = threading.Lock()


def _job_run_pipeline():
    """The job that runs the autonomous pipeline."""
    try:
        from autonomous_agent import run_pipeline
        from agent_state import mark_file_seen, add_error
        
        logger.info("=" * 60)
        logger.info("🔄 AUTONOMOUS PIPELINE STARTED (Scheduled)")
        logger.info("=" * 60)
        
        result = run_pipeline()
        
        # Log result
        if result.get("errors"):
            for error in result["errors"]:
                add_error(error)
                logger.error(f"  ❌ {error}")
        
        logger.info(f"✅ Pipeline completed: {result.get('message', 'Done')}")
        logger.info(f"   Files processed: {result.get('files_processed', 0)}")
        logger.info(f"   Rows added: {result.get('total_rows_added', 0)}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Pipeline error: {e}", exc_info=True)
        try:
            from agent_state import add_error
            add_error(str(e))
        except:
            pass


def start_scheduler():
    """
    Start the background scheduler.
    Runs autonomous pipeline daily at 10 PM ET.
    
    On Replit, requires "Always-On" mode enabled.
    """
    global _scheduler
    
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            logger.info("⚠️  Scheduler already running")
            return
        
        try:
            _scheduler = BackgroundScheduler()
            
            # Schedule job for 10 PM ET daily
            # 10 PM ET = 2 AM UTC (EDT, roughly March-Nov)
            #            3 AM UTC (EST, roughly Nov-March)
            # Using 2 AM UTC as compromise
            _scheduler.add_job(
                _job_run_pipeline,
                CronTrigger(hour=2, minute=0),  # 10 PM ET / 2 AM UTC
                id='daily_autonomous_pipeline',
                name='Daily Autonomous Opportunity Processing',
                replace_existing=True,
                timezone='UTC'
            )
            
            _scheduler.start()
            logger.info("✅ Background scheduler started")
            logger.info("   Job: Daily Autonomous Pipeline")
            logger.info("   Time: 10 PM ET (2 AM UTC) daily")
            logger.info("   Next run will be shown below...")
            
            # Show next run time
            jobs = _scheduler.get_jobs()
            if jobs:
                job = jobs[0]
                next_run = job.next_run_time
                logger.info(f"   Next run: {next_run}")
            
        except Exception as e:
            logger.error(f"❌ Failed to start scheduler: {e}", exc_info=True)
            _scheduler = None


def stop_scheduler():
    """Stop the background scheduler."""
    global _scheduler
    
    with _scheduler_lock:
        if _scheduler is None or not _scheduler.running:
            logger.info("⚠️  Scheduler not running")
            return
        
        try:
            _scheduler.shutdown()
            _scheduler = None
            logger.info("✅ Scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")


def get_scheduler_status() -> dict:
    """Get current scheduler status."""
    global _scheduler
    
    if _scheduler is None:
        return {
            "running": False,
            "message": "Scheduler not started"
        }
    
    if not _scheduler.running:
        return {
            "running": False,
            "message": "Scheduler created but not running"
        }
    
    jobs = _scheduler.get_jobs()
    if not jobs:
        return {
            "running": True,
            "message": "Scheduler running but no jobs scheduled"
        }
    
    job = jobs[0]
    return {
        "running": True,
        "job_name": job.name,
        "job_id": job.id,
        "next_run": str(job.next_run_time),
        "trigger": str(job.trigger)
    }


def force_run_now():
    """Force run the pipeline immediately (for testing)."""
    try:
        logger.info("🔄 Forcing immediate pipeline run...")
        _job_run_pipeline()
        logger.info("✅ Immediate run completed")
        return {"status": "ok", "message": "Pipeline run completed"}
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}
