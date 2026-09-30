"""Gmail API client wrapper."""

import base64
import logging
from email.message import EmailMessage
from typing import Any, Optional

import httpx

from app.notifications.base import NotificationProviderError
from app.notifications.gmail.config import GmailConfig
from app.notifications.oauth import (
    GoogleOAuthClient,
    OAuthAuthenticationError,
    OAuthConfigurationError,
)
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailClient:
    """Client for interacting with the Gmail API via HTTP REST."""

    def __init__(
        self,
        config: GmailConfig,
        oauth_client: GoogleOAuthClient,
        http_client: Optional[httpx.Client] = None,
        base_url: str = GMAIL_SEND_URL,
    ) -> None:
        self.config = config
        self.oauth_client = oauth_client
        self._http_client = http_client
        self.base_url = base_url

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=10.0)

    def send_email(
        self,
        recipient_email: str,
        subject: str,
        body: str,
    ) -> dict[str, Any]:
        """Send an email using the Gmail API.

        Args:
            recipient_email: The destination email address.
            subject: The email subject line.
            body: The email body text.

        Returns:
            The JSON response from the Gmail API containing message ID and threadId.

        Raises:
            NotificationProviderError: On API failure, network error, or auth error.
        """
        if not recipient_email or "@" not in recipient_email:
            raise NotificationProviderError(f"Invalid recipient email: '{recipient_email}'")

        try:
            access_token = self.oauth_client.get_valid_access_token()
        except (OAuthAuthenticationError, OAuthConfigurationError) as exc:
            safe_err = redact_string(str(exc))
            raise NotificationProviderError(f"Gmail authorization error: {safe_err}") from exc

        # Create RFC 5322 MIME email
        message = EmailMessage()
        message.set_content(body)
        message["To"] = recipient_email
        message["From"] = self.config.sender_email or "me"
        message["Subject"] = subject

        # Base64url encode for Gmail API
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        payload = {"raw": encoded_message}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        client = self._get_http_client()

        try:
            response = client.post(self.base_url, json=payload, headers=headers)

            # If 401 Unauthorized, attempt a single token refresh and retry
            if response.status_code == 401:
                logger.warning("Gmail API returned 401 Unauthorized; attempting access token refresh...")
                try:
                    new_token = self.oauth_client.refresh_access_token()
                    headers["Authorization"] = f"Bearer {new_token.access_token}"
                    response = client.post(self.base_url, json=payload, headers=headers)
                except Exception as refresh_exc:
                    safe_refresh_err = redact_string(str(refresh_exc))
                    logger.error("Token refresh failed following 401: %s", safe_refresh_err)
                    raise NotificationProviderError(
                        f"Gmail API rejected token as unauthorized and refresh failed: {safe_refresh_err}"
                    ) from refresh_exc

            if response.status_code == 200:
                data = response.json()
                msg_id = data.get("id", "unknown")
                logger.info("Successfully sent Gmail message (ID: %s)", msg_id)
                return {
                    "id": msg_id,
                    "threadId": data.get("threadId"),
                }

            if response.status_code == 401:
                raise NotificationProviderError("Gmail API rejected token as unauthorized.")

            error_msg = self._extract_error(response)
            raise NotificationProviderError(
                f"Gmail API error HTTP {response.status_code}: {error_msg}"
            )

        except httpx.TimeoutException as exc:
            raise NotificationProviderError("Network timeout connecting to Gmail API.") from exc
        except httpx.RequestError as exc:
            clean_err = redact_string(str(exc))
            raise NotificationProviderError(f"Network error connecting to Gmail API: {clean_err}") from exc

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        """Safely extract error message without leaking sensitive information."""
        try:
            data = response.json()
            if isinstance(data, dict):
                error_obj = data.get("error", {})
                if isinstance(error_obj, dict):
                    msg = error_obj.get("message") or error_obj.get("status")
                    if msg:
                        return redact_string(str(msg))
                return redact_string(str(data))
            return redact_string(str(data))
        except Exception:
            return redact_string(response.text[:200])
