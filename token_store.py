"""
Token store: reads OAuth tokens written by the Replit connector system.
Tokens are written to .connector_tokens.json by the token_writer.js helper
which runs in the code_execution sandbox where listConnections() is available.
Python reads from this file for all Google API calls.
"""
import json
import time
from pathlib import Path

TOKEN_FILE = Path(".connector_tokens.json")
TOKEN_MAX_AGE_SECS = 3000  # refresh if older than 50 minutes


def get_token(connector: str) -> str:
    """
    Read a token for the given connector ('google-drive' or 'google-sheet').
    Raises RuntimeError if token file is missing or stale.
    """
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "Connector token file not found. Please run the pipeline from the "
            "Autonomous Agent page in the app, which refreshes tokens automatically."
        )

    data = json.loads(TOKEN_FILE.read_text())
    entry = data.get(connector)
    if not entry:
        raise RuntimeError(f"No token for connector '{connector}' in token store.")

    written_at = entry.get("written_at", 0)
    age = time.time() - written_at
    if age > TOKEN_MAX_AGE_SECS:
        raise RuntimeError(
            f"Token for '{connector}' is {int(age/60)} minutes old (max 50). "
            "Please trigger a fresh run from the Autonomous Agent page."
        )

    return entry["access_token"]


def write_tokens(drive_token: str, sheet_token: str):
    """Write fresh tokens to the token store file (called from Python when tokens are injected)."""
    now = time.time()
    data = {
        "google-drive": {"access_token": drive_token, "written_at": now},
        "google-sheet": {"access_token": sheet_token, "written_at": now},
    }
    TOKEN_FILE.write_text(json.dumps(data))
