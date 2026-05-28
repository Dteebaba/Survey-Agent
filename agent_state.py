"""
Agent State Management - Tracks what files have been processed
to prevent reprocessing and maintain audit trail.
"""

import json
import os
from datetime import datetime

STATE_FILE = "agent_state.json"


def _load_state():
    """Load state from JSON file, or return default."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                return _ensure_keys(state)
        except Exception as e:
            print(f"Error loading state: {e}")
    return _default_state()


def _default_state():
    return {
        "last_processed_file_id": None,
        "last_processed_file_name": None,
        "last_processed_date": None,
        "files_processed": [],
        "last_run_time": None,
        "total_rows_added": 0,
        "total_files_processed": 0,
        "errors": [],
    }


def _ensure_keys(state: dict) -> dict:
    """Ensure all required keys exist — fixes old/partial state files."""
    defaults = _default_state()
    for key, val in defaults.items():
        state.setdefault(key, val)
    return state


def _save_state(state):
    """Save state to JSON file."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Error saving state: {e}")


# -------------------------------------------------
# PUBLIC API
# -------------------------------------------------


def get_state():
    return _load_state()


def get_last_processed_file_id():
    return _load_state().get("last_processed_file_id")


def get_last_processed_file_name():
    return _load_state().get("last_processed_file_name")


def get_last_run_time():
    ts = _load_state().get("last_run_time")
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except:
            return None
    return None


def is_file_seen(file_id):
    return get_last_processed_file_id() == file_id


def mark_file_seen(file_id, file_name, rows_added, status="ok"):
    state = _load_state()
    state["last_processed_file_id"] = file_id
    state["last_processed_file_name"] = file_name
    state["last_processed_date"] = datetime.utcnow().isoformat()
    state["last_run_time"] = datetime.utcnow().isoformat()
    state["total_rows_added"] += rows_added
    state["total_files_processed"] += 1
    state["files_processed"].append(
        {
            "id": file_id,
            "name": file_name,
            "rows_added": rows_added,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
    # Keep only last 100 entries
    if len(state["files_processed"]) > 100:
        state["files_processed"] = state["files_processed"][-100:]
    _save_state(state)


def add_error(message):
    state = _load_state()
    state["errors"].append(
        {"message": message, "timestamp": datetime.utcnow().isoformat()}
    )
    if len(state["errors"]) > 50:
        state["errors"] = state["errors"][-50:]
    _save_state(state)


def get_summary():
    state = _load_state()
    last_run = state.get("last_run_time", "Never")
    if last_run != "Never":
        try:
            dt = datetime.fromisoformat(last_run)
            last_run = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            pass
    return {
        "last_file_processed": state.get("last_processed_file_name", "None"),
        "last_run_time": last_run,
        "total_files_processed": state.get("total_files_processed", 0),
        "total_rows_added": state.get("total_rows_added", 0),
        "recent_errors": state.get("errors", [])[-5:],
    }


def reset_state():
    _save_state(_default_state())
