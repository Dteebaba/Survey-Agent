"""
Agent State — persists run history and file tracking.

State is stored in two places so it survives anywhere:
  1. Local file  (agent_state.json) — fast, in-process cache
  2. GitHub Gist — synced on startup and after every write;
                   shared between GitHub Actions runs and Streamlit Cloud

Call sync_from_gist() once at startup (pipeline_job.py and app.py do this).
Every _save() writes locally AND pushes to the Gist.
"""

import json
import os
from datetime import datetime

import requests

STATE_FILE   = "agent_state.json"
GIST_FILE    = "agent_state.json"       # filename inside the Gist
_GIST_ID     = os.getenv("GIST_ID", "")
# Accept GH_TOKEN (Streamlit Cloud secret name) or GITHUB_TOKEN (workflow env var)
_GIST_TOKEN  = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN", "")


# ─────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────

def _default() -> dict:
    return {
        "processed_file_ids":       [],
        "processed_files":          [],
        "last_processed_file_id":   None,
        "last_processed_file_name": None,
        "last_run_time":            None,
        "total_rows_added":         0,
        "total_files_processed":    0,
        "run_log":                  [],
        "errors":                   [],
        "pipeline_lock":            {"running": False},
        "user_activity_log":        [],
    }


def _ensure(state: dict) -> dict:
    for k, v in _default().items():
        state.setdefault(k, v)
    return state


# ─────────────────────────────────────────────
# Gist helpers
# ─────────────────────────────────────────────

def _gist_headers() -> dict:
    return {
        "Authorization": f"token {_GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _load_from_gist() -> dict | None:
    if not _GIST_ID or not _GIST_TOKEN:
        return None
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{_GIST_ID}",
            headers=_gist_headers(),
            timeout=8,
        )
        if resp.status_code == 200:
            files = resp.json().get("files", {})
            if GIST_FILE in files:
                return _ensure(json.loads(files[GIST_FILE]["content"]))
    except Exception as e:
        print(f"[agent_state] Gist load error: {e}")
    return None


def _save_to_gist(state: dict):
    if not _GIST_ID or not _GIST_TOKEN:
        return
    try:
        resp = requests.patch(
            f"https://api.github.com/gists/{_GIST_ID}",
            headers=_gist_headers(),
            json={"files": {GIST_FILE: {"content": json.dumps(state, indent=2)}}},
            timeout=10,
        )
        if resp.status_code == 200:
            print("[agent_state] ✅ State saved to Gist")
        else:
            print(f"[agent_state] ⚠️  Gist save returned {resp.status_code}")
    except Exception as e:
        print(f"[agent_state] Gist save error: {e}")


# ─────────────────────────────────────────────
# Local file helpers
# ─────────────────────────────────────────────

def _load_local() -> dict | None:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return _ensure(json.load(f))
        except Exception as e:
            print(f"[agent_state] Local load error: {e}")
    return None


def _save_local(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[agent_state] Local save error: {e}")


# ─────────────────────────────────────────────
# Core load / save
# ─────────────────────────────────────────────

def _load() -> dict:
    """Read from local file (fast path). Falls back to default."""
    return _load_local() or _default()


def _save(state: dict):
    """Write to local file and push to Gist."""
    _save_local(state)
    _save_to_gist(state)


# ─────────────────────────────────────────────
# Public: startup sync
# ─────────────────────────────────────────────

def sync_from_gist():
    """
    Pull the latest state from the Gist and cache it locally.
    Call once at startup (pipeline_job.py and app.py).
    No-op if Gist is not configured.
    """
    gist_state = _load_from_gist()
    if gist_state is not None:
        _save_local(gist_state)
        print("[agent_state] ✅ Synced state from GitHub Gist")
    else:
        print("[agent_state] ℹ️  Gist not configured — using local state file")


# ─────────────────────────────────────────────
# File-level tracking
# ─────────────────────────────────────────────

def get_state() -> dict:
    return _load()


def get_processed_file_ids() -> set:
    return set(_load().get("processed_file_ids", []))


def get_last_processed_file_id() -> str | None:
    return _load().get("last_processed_file_id")


def get_last_run_time() -> datetime | None:
    ts = _load().get("last_run_time")
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None
    return None


def is_file_seen(file_id: str) -> bool:
    return file_id in get_processed_file_ids()


def mark_file_seen(file_id: str, file_name: str, rows_added: int, status: str = "ok"):
    state = _load()

    ids = state.get("processed_file_ids", [])
    if file_id not in ids:
        ids.append(file_id)
    state["processed_file_ids"] = ids

    state["last_processed_file_id"]   = file_id
    state["last_processed_file_name"] = file_name
    state["last_run_time"]            = datetime.utcnow().isoformat()
    state["total_rows_added"]        += rows_added
    state["total_files_processed"]   += 1

    state["processed_files"].append({
        "id":         file_id,
        "name":       file_name,
        "rows_added": rows_added,
        "status":     status,
        "timestamp":  datetime.utcnow().isoformat(),
    })

    if len(state["processed_files"]) > 500:
        state["processed_files"] = state["processed_files"][-500:]

    _save(state)


# ─────────────────────────────────────────────
# Run-level logging
# ─────────────────────────────────────────────

def record_run(triggered_by: str, summary: dict):
    """
    Persist one pipeline invocation to the run log.
    triggered_by: "scheduled" | "manual"
    """
    state = _load()

    errors          = summary.get("errors", [])
    files_processed = summary.get("files_processed", 0)

    if errors:
        run_status = "error"
    elif files_processed == 0:
        run_status = "no_new_files"
    else:
        run_status = "success"

    entry = {
        "timestamp":       datetime.utcnow().isoformat(),
        "triggered_by":    triggered_by,
        "files_checked":   summary.get("files_checked", 0),
        "files_processed": files_processed,
        "rows_added":      summary.get("total_rows_added", 0),
        "status":          run_status,
        "message":         summary.get("message", ""),
        "errors":          errors,
        "processed_files": [
            {"name": f["name"], "rows_added": f.get("rows_added", 0)}
            for f in summary.get("processed_files", [])
        ],
    }

    state["run_log"].append(entry)
    if len(state["run_log"]) > 200:
        state["run_log"] = state["run_log"][-200:]

    _save(state)


def get_run_log() -> list:
    """Return run log, most recent first."""
    return list(reversed(_load().get("run_log", [])))


# ─────────────────────────────────────────────
# Error log
# ─────────────────────────────────────────────

def add_error(message: str):
    state = _load()
    state["errors"].append({
        "message":   message,
        "timestamp": datetime.utcnow().isoformat(),
    })
    if len(state["errors"]) > 100:
        state["errors"] = state["errors"][-100:]
    _save(state)


# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────

def get_summary() -> dict:
    state = _load()

    last_run = state.get("last_run_time", "Never")
    if last_run and last_run != "Never":
        try:
            last_run = datetime.fromisoformat(last_run).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass

    run_log       = state.get("run_log", [])
    last_run_entry = run_log[-1] if run_log else None

    return {
        "last_file_processed":   state.get("last_processed_file_name") or "—",
        "last_run_time":         last_run or "Never",
        "total_files_processed": state.get("total_files_processed", 0),
        "total_rows_added":      state.get("total_rows_added", 0),
        "processed_file_count":  len(state.get("processed_file_ids", [])),
        "last_run_entry":        last_run_entry,
        "recent_errors":         state.get("errors", [])[-10:],
        "run_log":               run_log,
        "processed_files":       state.get("processed_files", []),
    }


# ─────────────────────────────────────────────
# Reset
# ─────────────────────────────────────────────

def reset_state():
    """Full reset — next run will process ALL files from scratch."""
    _save(_default())


# ─────────────────────────────────────────────
# Pipeline lock
# ─────────────────────────────────────────────

def set_pipeline_running(username: str):
    state = _load()
    state["pipeline_lock"] = {
        "running":    True,
        "username":   username,
        "started_at": datetime.utcnow().isoformat(),
    }
    _save(state)


def clear_pipeline_running():
    state = _load()
    state["pipeline_lock"] = {"running": False}
    _save(state)


def is_pipeline_running() -> tuple:
    """Returns (is_running: bool, username: str|None, started_at: str|None)."""
    lock = _load().get("pipeline_lock", {})
    if lock.get("running"):
        return True, lock.get("username", "?"), lock.get("started_at", "")
    return False, None, None


# ─────────────────────────────────────────────
# User activity log
# ─────────────────────────────────────────────

def log_user_activity(username: str, action: str, details: dict = None):
    """
    Log a user action. action examples:
      "login", "logout", "progress_update"
    details for progress_update:
      {"solicitation": str, "old_status": str, "new_status": str}
    """
    state = _load()
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "username":  username,
        "action":    action,
    }
    if details:
        entry.update(details)
    state["user_activity_log"].append(entry)
    if len(state["user_activity_log"]) > 20000:
        state["user_activity_log"] = state["user_activity_log"][-20000:]
    _save(state)


def get_user_activity_log(
    username: str = None,
    from_dt: datetime = None,
    to_dt: datetime = None,
) -> list:
    """Return activity log, most recent first, with optional filters."""
    entries = _load().get("user_activity_log", [])
    if username:
        entries = [e for e in entries if e.get("username") == username]
    if from_dt:
        entries = [e for e in entries if e.get("timestamp", "") >= from_dt.isoformat()]
    if to_dt:
        entries = [e for e in entries if e.get("timestamp", "") <= to_dt.isoformat()]
    return list(reversed(entries))
