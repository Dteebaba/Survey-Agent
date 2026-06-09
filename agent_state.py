"""
Agent State v2 — tracks ALL processed file IDs (not just the last one).
This enables skipping any previously processed file on every run.
"""

import json
import os
from datetime import datetime

STATE_FILE = "agent_state.json"


def _default():
    return {
        "processed_file_ids": [],          # list of ALL processed file IDs
        "processed_files":    [],          # audit log with details
        "last_processed_file_id":   None,  # convenience — most recent
        "last_processed_file_name": None,
        "last_run_time":            None,
        "total_rows_added":         0,
        "total_files_processed":    0,
        "errors":                   [],
    }


def _ensure(state: dict) -> dict:
    for k, v in _default().items():
        state.setdefault(k, v)
    return state


def _load() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return _ensure(json.load(f))
        except Exception as e:
            print(f"State load error: {e}")
    return _default()


def _save(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"State save error: {e}")


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def get_state() -> dict:
    return _load()


def get_processed_file_ids() -> set:
    """Return set of ALL file IDs we've already processed."""
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

    # Add to processed IDs set
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

    # Keep audit log at max 200 entries
    if len(state["processed_files"]) > 200:
        state["processed_files"] = state["processed_files"][-200:]

    _save(state)


def add_error(message: str):
    state = _load()
    state["errors"].append({
        "message":   message,
        "timestamp": datetime.utcnow().isoformat(),
    })
    if len(state["errors"]) > 50:
        state["errors"] = state["errors"][-50:]
    _save(state)


def get_summary() -> dict:
    state = _load()
    last_run = state.get("last_run_time", "Never")
    if last_run and last_run != "Never":
        try:
            last_run = datetime.fromisoformat(last_run).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass
    return {
        "last_file_processed":    state.get("last_processed_file_name") or "None",
        "last_run_time":          last_run or "Never",
        "total_files_processed":  state.get("total_files_processed", 0),
        "total_rows_added":       state.get("total_rows_added", 0),
        "processed_file_count":   len(state.get("processed_file_ids", [])),
        "recent_errors":          state.get("errors", [])[-5:],
    }


def reset_state():
    """Full reset — next run will process ALL files from scratch."""
    _save(_default())