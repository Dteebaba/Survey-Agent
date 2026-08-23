"""
Token Store - Uses Google Service Account for permanent, never-expiring auth.
Service account JSON stored in GOOGLE_SERVICE_ACCOUNT_JSON environment variable
(Streamlit Cloud secrets or GitHub Actions secrets).
"""

import os
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE = {"token": None, "expires_at": None}


def _utc_expiry(value, fallback: datetime) -> datetime:
    """Normalize google-auth's sometimes-naive UTC expiry timestamp."""
    if value is None:
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _get_service_account_credentials():
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not set. "
            "Add it to Streamlit Cloud secrets and GitHub Actions secrets."
        )
    try:
        return json.loads(sa_json)
    except Exception as e:
        raise ValueError(f"Invalid service account JSON: {e}")


def get_token(service: str = "google-drive") -> str:
    """
    Get a valid Bearer token using the service account.
    Automatically refreshes — never expires.
    """
    now = datetime.now(timezone.utc)
    if (_TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] and
            now < _TOKEN_CACHE["expires_at"] - timedelta(minutes=5)):
        return _TOKEN_CACHE["token"]

    try:
        _TOKEN_LOCK.acquire()
        now = datetime.now(timezone.utc)
        if (_TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] and
                now < _TOKEN_CACHE["expires_at"] - timedelta(minutes=5)):
            return _TOKEN_CACHE["token"]
        import google.auth.transport.requests
        import google.oauth2.service_account

        sa_info = _get_service_account_credentials()

        credentials = google.oauth2.service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/drive"]
        )

        # Refresh to get access token
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)

        _TOKEN_CACHE["token"] = credentials.token
        _TOKEN_CACHE["expires_at"] = _utc_expiry(
            credentials.expiry, now + timedelta(minutes=50)
        )

        logger.info("✅ Service account token obtained")
        return credentials.token

    except Exception as e:
        logger.error(f"Service account auth failed: {e}")
        raise
    finally:
        if _TOKEN_LOCK.locked():
            _TOKEN_LOCK.release()


def get_proxy_config() -> dict:
    """Return proxy config for google_connector._drive_request()"""
    token = get_token()
    return {
        "proxy_url": "https://www.googleapis.com",
        "proxy_headers": {"Authorization": f"Bearer {token}"},
    }


def clear_tokens():
    """No-op for service accounts — they auto-refresh."""
    logger.info("Service account tokens auto-refresh — no cache to clear")


def save_token(service: str, token: str) -> bool:
    """No-op for service accounts."""
    return True
