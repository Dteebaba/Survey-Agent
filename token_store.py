"""
Token Store - Uses Google Service Account for permanent, never-expiring auth.
Service account JSON stored in GOOGLE_SERVICE_ACCOUNT_JSON Replit Secret.
"""

import os
import json
import logging

logger = logging.getLogger(__name__)


def _get_service_account_credentials():
    """Load service account credentials from Replit Secret."""
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON secret not found.\n"
            "Add it in Replit Secrets."
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
    try:
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

        logger.info("✅ Service account token obtained")
        return credentials.token

    except Exception as e:
        logger.error(f"Service account auth failed: {e}")
        raise


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