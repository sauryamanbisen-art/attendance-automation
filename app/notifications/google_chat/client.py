"""HTTP client for official Google Chat REST API v1."""

import logging
from typing import Any, Optional

import httpx

from app.notifications.google_chat.exceptions import (
    GoogleChatApiError,
    GoogleChatPermissionError,
    GoogleChatRateLimitError,
    GoogleChatRecipientError,
    OAuthAuthenticationError,
)
from app.notifications.google_chat.oauth import GoogleChatOAuthClient
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)

GOOGLE_CHAT_API_BASE = "https://chat.googleapis.com/v1"


class GoogleChatClient:
    """Client for Google Chat API v1 using OAuth 2.0 authorization."""

    def __init__(
        self,
        oauth_client: GoogleChatOAuthClient,
        http_client: Optional[httpx.Client] = None,
        base_url: str = GOOGLE_CHAT_API_BASE,
    ) -> None:
        self.oauth_client = oauth_client
        self._http_client = http_client
        self.base_url = base_url.rstrip("/")

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=10.0)

    @staticmethod
    def normalize_space_name(space_name: str) -> str:
        """Ensure space name is properly formatted with 'spaces/' prefix."""
        cleaned = space_name.strip()
        if not cleaned:
            raise GoogleChatRecipientError("Chat space name cannot be empty.")
        if not cleaned.startswith("spaces/"):
            return f"spaces/{cleaned}"
        return cleaned

    def send_message(
        self,
        space_name: str,
        text: str,
        cards: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Send a message to a Google Chat space.

        Args:
            space_name: Target space name or ID (e.g. 'spaces/AAAA123' or 'AAAA123').
            text: Plaintext message fallback or primary content.
            cards: Optional cardsV2 payload for rich formatting.

        Returns:
            Dictionary response from Google Chat API containing created message details.

        Raises:
            OAuthAuthenticationError: If token is missing, expired, or invalid.
            GoogleChatPermissionError: If caller lacks permissions (403).
            GoogleChatRecipientError: If space does not exist (404) or is empty.
            GoogleChatRateLimitError: If rate limit exceeded (429).
            GoogleChatApiError: For unexpected HTTP errors or network timeouts.
        """
        formatted_space = self.normalize_space_name(space_name)
        url = f"{self.base_url}/{formatted_space}/messages"

        # Obtain valid token from OAuth client
        token = self.oauth_client.get_valid_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        body: dict[str, Any] = {"text": text}
        if cards:
            body["cardsV2"] = cards

        try:
            client = self._get_http_client()
            response = client.post(url, json=body, headers=headers)
            return self._handle_response(response, formatted_space)
        except httpx.TimeoutException as exc:
            logger.error("Timeout connecting to Google Chat API for space %s", formatted_space)
            raise GoogleChatApiError("Network timeout while calling Google Chat API.") from exc
        except httpx.RequestError as exc:
            clean_err = redact_string(str(exc))
            logger.error("Request error calling Google Chat API: %s", clean_err)
            raise GoogleChatApiError(f"Network error calling Google Chat API: {clean_err}") from exc

    def _handle_response(self, response: httpx.Response, space_name: str) -> dict[str, Any]:
        """Inspect HTTP response and map status codes to domain exceptions."""
        if response.status_code in (200, 201):
            return response.json()

        error_details = self._extract_error_detail(response)

        if response.status_code == 400:
            raise GoogleChatApiError(f"Bad Request from Google Chat API: {error_details}")
        elif response.status_code == 401:
            raise OAuthAuthenticationError(
                f"Google Chat API authentication failed (401 Unauthorized): {error_details}"
            )
        elif response.status_code == 403:
            raise GoogleChatPermissionError(
                f"Google Chat API permission denied (403 Forbidden). "
                f"Verify OAuth scopes and space membership: {error_details}"
            )
        elif response.status_code == 404:
            raise GoogleChatRecipientError(
                f"Google Chat space not found (404 Not Found): {space_name}. {error_details}"
            )
        elif response.status_code == 429:
            raise GoogleChatRateLimitError(
                f"Google Chat API rate limit exceeded (429 RESOURCE_EXHAUSTED): {error_details}"
            )
        elif 500 <= response.status_code < 600:
            raise GoogleChatApiError(
                f"Google Chat API server error ({response.status_code}): {error_details}"
            )
        else:
            raise GoogleChatApiError(
                f"Unexpected response from Google Chat API ({response.status_code}): {error_details}"
            )

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        """Extract error description safely from Google API JSON response."""
        try:
            data = response.json()
            error = data.get("error", {})
            if isinstance(error, dict):
                msg = error.get("message") or error.get("status")
                if msg:
                    return redact_string(str(msg))
            return redact_string(str(data))
        except Exception:
            return redact_string(response.text[:200])
