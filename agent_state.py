import json
import os
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("agent_state.json")


def _load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "seen_file_ids": [],
        "last_run": None,
        "last_run_status": None,
        "last_run_rows_added": 0,
        "last_run_file": None,
        "last_reviewed_file": None,
        "last_reviewed_time": None,
        "last_appended_file": None,
        "last_appended_time": None,
        "last_appended_rows": 0,
        "run_history": [],
    }


def _save(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def get_state() -> dict:
    return _load()


def mark_file_seen(file_id: str, file_name: str, rows_added: int, status: str = "ok", error: str = None):
    state = _load()
    if file_id not in state["seen_file_ids"]:
        state["seen_file_ids"].append(file_id)

    now = datetime.utcnow().isoformat()
    state["last_run"] = now
    state["last_run_status"] = status
    state["last_run_rows_added"] = rows_added
    state["last_run_file"] = file_name

    # Always update "last reviewed" — every file scanned counts
    state["last_reviewed_file"] = file_name
    state["last_reviewed_time"] = now

    # Only update "last appended" when rows were actually written
    if rows_added > 0:
        state["last_appended_file"] = file_name
        state["last_appended_time"] = now
        state["last_appended_rows"] = rows_added

    entry = {
        "timestamp": now,
        "file_id": file_id,
        "file_name": file_name,
        "rows_added": rows_added,
        "status": status,
    }
    if error:
        entry["error"] = error

    history = state.get("run_history", [])
    history.insert(0, entry)
    state["run_history"] = history[:50]

    _save(state)


def is_file_seen(file_id: str) -> bool:
    return file_id in _load()["seen_file_ids"]


def get_last_run_time() -> datetime | None:
    lr = _load().get("last_run")
    if lr:
        try:
            return datetime.fromisoformat(lr)
        except Exception:
            pass
    return None
