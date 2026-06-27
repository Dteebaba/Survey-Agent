"""
Standalone pipeline entry point.

Used by GitHub Actions for the nightly 10 PM ET scheduled run.
Can also be run manually from the terminal:

    python pipeline_job.py

Requires these environment variables (set as GitHub Actions secrets
or in a local .env file):
    GOOGLE_SERVICE_ACCOUNT_JSON   — service account key JSON string
    GOOGLE_DRIVE_FOLDER_ID        — Drive folder containing opportunity files
    GOOGLE_SHEETS_ID              — master output spreadsheet ID
    GIST_ID                       — GitHub Gist ID for persistent state
    GITHUB_TOKEN                  — PAT with gist scope
"""

import logging
import os
import sys
from datetime import datetime

# Load .env for local runs
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def main():
    log.info("=" * 60)
    log.info("ALMOR LLC — NIGHTLY OPPORTUNITY PIPELINE")
    log.info("Started: %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    # Pull latest state from Gist before doing anything
    try:
        from agent_state import sync_from_gist
        sync_from_gist()
    except Exception as e:
        log.warning("Could not sync state from Gist: %s", e)

    # Run pipeline
    try:
        from autonomous_agent import run_pipeline
        from agent_state import record_run

        log.info("Running pipeline…")
        summary = run_pipeline()

        # Persist the run result (writes locally + to Gist)
        record_run("scheduled", summary)

        rows           = summary.get("total_rows_added", 0)
        files_done     = summary.get("files_processed", 0)
        files_checked  = summary.get("files_checked", 0)
        errors         = summary.get("errors", [])
        message        = summary.get("message", "")

        log.info("-" * 60)
        log.info("Files checked   : %d", files_checked)
        log.info("Files processed : %d", files_done)
        log.info("Rows added      : %d", rows)
        log.info("Message         : %s", message)

        if errors:
            log.error("Errors encountered:")
            for err in errors:
                log.error("  ❌ %s", err)
            log.info("=" * 60)
            sys.exit(1)

        if files_done == 0:
            log.info("ℹ️  No new files to process — sheet is up to date.")
        else:
            log.info("✅ Pipeline complete — %d row(s) added to master sheet.", rows)

        # Print Gist sync confirmation so we can verify state was saved
        gist_id = os.getenv("GIST_ID", "")
        gh_token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN", "")
        if gist_id and gh_token:
            log.info("🔗 Gist state sync: GIST_ID=%s…  token=%s…",
                     gist_id[:8], gh_token[:8])
        else:
            log.warning("⚠️  Gist state sync SKIPPED — GIST_ID or GH_TOKEN not set")

        log.info("=" * 60)

    except Exception as exc:
        log.exception("FATAL pipeline error: %s", exc)
        try:
            from agent_state import add_error
            add_error(f"GitHub Actions fatal error: {exc}")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
