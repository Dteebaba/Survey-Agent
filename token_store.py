"""
Token Store - Gets Google OAuth credentials via Replit's Connection system.

Strategy (in order):
  1. Replit connectors proxy (node refresh_token.js → .connector_tokens.json)
     Works in dev AND deployed — the Node.js SDK auto-refreshes Paseto auth.
  2. GOOGLE_ACCESS_TOKEN secret (manual override, may be expired)

get_proxy_config() → returns {proxy_url, proxy_headers} for use in google_connector.py
get_token()       → legacy bearer-token path (kept for compatibility)
"""

import json
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

TOKENS_FILE = ".connector_tokens.json"
# Refresh proxy headers if older than this many seconds (tokens live ~1h)
PROXY_TTL = 45 * 60  # 45 minutes


# -------------------------------------------------
# Public API
# -------------------------------------------------

def get_proxy_config() -> dict:
    """
    Return {proxy_url, proxy_headers} for Replit's connectors proxy.
    Automatically refreshes via node refresh_token.js when stale.
    """
    cached = _load_proxy_cache()
    if cached:
        return cached

    _refresh_via_node()
    cached = _load_proxy_cache(allow_stale=True)
    if cached:
        return cached

    raise RuntimeError(
        "❌ Could not obtain Replit connectors proxy config.\n"
        "Make sure node is available and refresh_token.js is present."
    )


def get_token(service: str) -> str:
    """
    Legacy: get a raw Bearer access token.
    Falls back to GOOGLE_ACCESS_TOKEN secret if proxy approach not available.
    """
    if service != "google-drive":
        raise ValueError(f"Unknown service: {service}")

    # Try to get from cached token file (written by node refresh_token.js)
    raw = _load_raw_access_token()
    if raw:
        return raw

    # Manual override (may be expired)
    raw_token = os.getenv("GOOGLE_ACCESS_TOKEN")
    if raw_token:
        logger.warning(
            "⚠️  Using GOOGLE_ACCESS_TOKEN from Secrets — this may be stale."
        )
        return raw_token

    raise ValueError(
        "❌ No Google Drive token found.\n"
        "Ensure the Google Drive integration is connected and "
        "refresh_token.js can run."
    )


# -------------------------------------------------
# Internal helpers
# -------------------------------------------------

def _load_proxy_cache(allow_stale: bool = False) -> dict | None:
    """Read proxy config from cache file; return None if missing/stale."""
    try:
        with open(TOKENS_FILE) as f:
            data = json.load(f)
        entry = data.get("google-drive", {})
        proxy_url = entry.get("proxy_url")
        proxy_headers = entry.get("proxy_headers")
        written_at = entry.get("written_at", 0)

        if not proxy_url or not proxy_headers:
            return None

        age = time.time() - written_at
        if not allow_stale and age > PROXY_TTL:
            logger.info(f"Proxy headers are {int(age)}s old — refreshing…")
            return None

        return {"proxy_url": proxy_url, "proxy_headers": proxy_headers}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def _load_raw_access_token() -> str | None:
    """Try to extract a raw access_token from the cache file (legacy)."""
    try:
        with open(TOKENS_FILE) as f:
            data = json.load(f)
        entry = data.get("google-drive", {})
        if isinstance(entry, dict):
            return entry.get("access_token")
        if isinstance(entry, str):
            return entry
    except Exception:
        pass
    return None


def _refresh_via_node() -> bool:
    """Run node refresh_token.js to write fresh proxy headers."""
    script = os.path.join(os.path.dirname(__file__), "refresh_token.js")
    if not os.path.exists(script):
        logger.error("refresh_token.js not found — cannot refresh proxy headers")
        return False
    try:
        result = subprocess.run(
            ["node", script],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.abspath(script)),
        )
        if result.returncode == 0:
            logger.info(f"✅ Token refreshed: {result.stdout.strip()}")
            return True
        else:
            logger.error(f"refresh_token.js failed: {result.stderr.strip()}")
            return False
    except Exception as e:
        logger.error(f"Could not run refresh_token.js: {e}")
        return False


def save_token(service: str, token: str) -> bool:
    """Manually save a token (kept for UI compatibility)."""
    try:
        tokens = {}
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE) as f:
                tokens = json.load(f)
        tokens[f"{service}_access_token"] = token
        with open(TOKENS_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
        logger.info(f"✅ Saved token for {service}")
        return True
    except Exception as e:
        logger.error(f"Error saving token: {e}")
        return False


def get_all_tokens() -> dict:
    """Get all stored tokens (for debugging)."""
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Error reading tokens: {e}")
    return {}


def clear_tokens() -> bool:
    """Clear all stored tokens so next call forces a refresh."""
    try:
        if os.path.exists(TOKENS_FILE):
            os.remove(TOKENS_FILE)
        logger.info("✅ Cleared all stored tokens")
        return True
    except Exception as e:
        logger.error(f"Error clearing tokens: {e}")
        return False
