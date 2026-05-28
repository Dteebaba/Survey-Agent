"""
Token Store - Gets Google OAuth tokens via Replit's Connection system.
Replit stores Google connections as conn_google-drive_XXXXX IDs,
not raw tokens. This file exchanges that connection for a live token.
"""

import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

TOKENS_FILE = ".connector_tokens.json"


def get_token(service: str) -> str:
    """
    Get OAuth access token for Google Drive via Replit's connection system.

    Your Replit Configurations show:
      GOOGLE_DRIVE_CONN_ID = conn_google-drive_01KSDA57A08JSFMSAYVQBYB8ZT

    We use that connection ID to get a live Bearer token.
    """

    if service == "google-drive":
        # Priority 1: Raw token directly in Secrets (manual override)
        raw_token = os.getenv("GOOGLE_ACCESS_TOKEN")
        if raw_token:
            logger.info("✅ Using GOOGLE_ACCESS_TOKEN from Secrets")
            return raw_token

        # Priority 2: Replit Connection ID (your current setup)
        conn_id = os.getenv("GOOGLE_DRIVE_CONN_ID")
        if conn_id:
            token = _exchange_replit_connection(conn_id)
            if token:
                return token

        # Priority 3: Local cached token file
        try:
            with open(TOKENS_FILE, "r") as f:
                tokens = json.load(f)
                token = tokens.get("google_access_token")
                if token:
                    logger.info("✅ Using cached token from file")
                    return token
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Could not read token file: {e}")

        raise ValueError(
            "❌ No Google Drive token found.\n"
            "Make sure GOOGLE_DRIVE_CONN_ID is set in Replit Configurations.\n"
            f"Current value: {os.getenv('GOOGLE_DRIVE_CONN_ID', 'NOT SET')}"
        )

    raise ValueError(f"Unknown service: {service}")


def _exchange_replit_connection(conn_id: str) -> str:
    """
    Exchange a Replit Connection ID for a live Google OAuth access token.
    Tries multiple Replit internal endpoints.
    """

    # Method 1: Replit token exchange endpoint
    try:
        resp = requests.post(
            "https://replit.com/data/connections/token",
            json={"connectionId": conn_id},
            headers={
                "X-Replit-User-Id": os.getenv("REPL_OWNER", ""),
                "X-Replit-Repl-Id": os.getenv("REPL_ID", ""),
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("access_token") or data.get("token")
            if token:
                logger.info("✅ Got token via Replit connection exchange")
                _cache_token(token)
                return token
    except Exception as e:
        logger.warning(f"Method 1 failed: {e}")

    # Method 2: Replit connections proxy
    try:
        resp = requests.get(
            f"https://connections.replit.com/token/{conn_id}",
            headers={"Authorization": f"Bearer {os.getenv('REPLIT_TOKEN', '')}"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("access_token") or data.get("token")
            if token:
                logger.info("✅ Got token via Replit proxy")
                _cache_token(token)
                return token
    except Exception as e:
        logger.warning(f"Method 2 failed: {e}")

    logger.error(
        "❌ Could not exchange Replit connection ID for token.\n"
        "Solution: Add GOOGLE_ACCESS_TOKEN manually to Replit Secrets.\n"
        "Get it from: https://developers.google.com/oauthplayground"
    )
    return None


def _cache_token(token: str):
    """Cache token locally for reuse."""
    try:
        tokens = {}
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r") as f:
                tokens = json.load(f)
        tokens["google_access_token"] = token
        with open(TOKENS_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not cache token: {e}")


def save_token(service: str, token: str) -> bool:
    """Manually save a token."""
    try:
        tokens = {}
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r") as f:
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
            with open(TOKENS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Error reading tokens: {e}")
    return {}


def clear_tokens() -> bool:
    """Clear all stored tokens."""
    try:
        if os.path.exists(TOKENS_FILE):
            os.remove(TOKENS_FILE)
        logger.info("✅ Cleared all stored tokens")
        return True
    except Exception as e:
        logger.error(f"Error clearing tokens: {e}")
        return False
