"""Shared Google OAuth 2.0 authentication, token management, and state storage.

This module provides provider-agnostic Google OAuth 2.0 implementations for
notification providers (Google Chat, Gmail, and future Google services).

Safety Guarantees:
- CSRF protection via cryptographically generated state with time-to-live expiration.
- Secrets (client_secret, access_token, refresh_token, code) are NEVER leaked or printed.
- Token storage strictly isolated to local-first secure storage (0600 file permissions).
- Fails closed safely if credentials are not configured, expired, or invalid.
"""

import json
import logging
import os
import secrets
import stat
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Protocol
from urllib.parse import urlencode

import httpx

from app.notifications.base import (
    NotificationConfigError,
    NotificationProviderError,
)

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Base Domain Exceptions for OAuth
# ═══════════════════════════════════════════════════════════════════════════


class OAuthError(NotificationProviderError):
    """Base exception for all OAuth-related operations."""

    pass


class OAuthConfigurationError(OAuthError, NotificationConfigError):
    """Raised when OAuth configuration is incomplete or missing."""

    pass


class OAuthAuthenticationError(OAuthError):
    """Raised when OAuth token exchange, refresh, or authorization fails."""

    pass


# ═══════════════════════════════════════════════════════════════════════════
# 2. Token Container & Storage
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class OAuthToken:
    """OAuth 2.0 token container with automatic credential masking."""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_at: Optional[float] = None
    scope: Optional[str] = None

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Return True if token is expired or expiring within buffer_seconds."""
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - buffer_seconds)

    def has_refresh_token(self) -> bool:
        """Return True if a refresh token is present."""
        return bool(self.refresh_token)

    def to_dict(self) -> dict[str, Any]:
        """Serialize token to dictionary for persistence."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OAuthToken":
        """Deserialize token from dictionary."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type", "Bearer"),
            expires_at=data.get("expires_at"),
            scope=data.get("scope"),
        )

    def __repr__(self) -> str:
        """Ensure tokens are NEVER printed in log files or tracebacks."""
        return (
            f"OAuthToken(access_token='[REDACTED]', "
            f"refresh_token={'[REDACTED]' if self.refresh_token else 'None'}, "
            f"token_type={self.token_type!r}, "
            f"expires_at={self.expires_at})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class BaseTokenStorage(ABC):
    """Abstract interface for storing and retrieving OAuth tokens securely."""

    @abstractmethod
    def load_token(self) -> Optional[OAuthToken]:
        """Retrieve stored token, or None if no token exists."""
        ...

    @abstractmethod
    def save_token(self, token: OAuthToken) -> None:
        """Persist OAuth token."""
        ...

    @abstractmethod
    def clear_token(self) -> None:
        """Delete stored token."""
        ...


class InMemoryTokenStorage(BaseTokenStorage):
    """Volatile in-memory token storage (ideal for testing, single sessions, dry-runs)."""

    def __init__(self, initial_token: Optional[OAuthToken] = None) -> None:
        self._token: Optional[OAuthToken] = initial_token

    def load_token(self) -> Optional[OAuthToken]:
        return self._token

    def save_token(self, token: OAuthToken) -> None:
        self._token = token

    def clear_token(self) -> None:
        self._token = None


class FileTokenStorage(BaseTokenStorage):
    """Secure local file token storage with restricted file permissions (0600)."""

    def __init__(self, file_path: str) -> None:
        self.file_path = os.path.abspath(file_path)

    def load_token(self) -> Optional[OAuthToken]:
        if not os.path.exists(self.file_path):
            return None
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return OAuthToken.from_dict(data)
        except Exception as exc:
            logger.warning("Failed to load OAuth token from %s: %s", self.file_path, exc)
            return None

    def save_token(self, token: OAuthToken) -> None:
        parent_dir = os.path.dirname(self.file_path)
        if parent_dir:
            os.makedirs(parent_dir, mode=0o700, exist_ok=True)
            try:
                os.chmod(parent_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 0700
            except OSError:
                pass

        # Write to temporary file first and set 0600 permissions
        temp_path = f"{self.file_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(token.to_dict(), f, indent=2)

        try:
            os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass  # Fallback on filesystems that don't support POSIX chmod

        os.replace(temp_path, self.file_path)
        try:
            os.chmod(self.file_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass

    def clear_token(self) -> None:
        if os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except OSError as exc:
                logger.warning("Failed to delete token file %s: %s", self.file_path, exc)


# ═══════════════════════════════════════════════════════════════════════════
# 3. OAuth State Manager (CSRF Protection)
# ═══════════════════════════════════════════════════════════════════════════


class OAuthStateManager:
    """In-memory CSRF state token manager with expiration and one-time consumption."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._states: dict[str, float] = {}

    def generate_state(self) -> str:
        """Generate a cryptographically secure state token and store with expiration."""
        self.cleanup_expired()
        state = secrets.token_urlsafe(32)
        self._states[state] = time.time() + self.ttl_seconds
        return state

    def validate_and_consume(self, state: Optional[str]) -> bool:
        """Validate state token and immediately consume it (one-time use).

        Returns:
            True if valid and not expired, False otherwise.
        """
        if not state:
            return False
        self.cleanup_expired()
        expires_at = self._states.pop(state, None)
        if expires_at is None:
            return False
        return time.time() <= expires_at

    def cleanup_expired(self) -> None:
        """Prune expired state tokens."""
        now = time.time()
        expired = [s for s, exp in self._states.items() if now > exp]
        for s in expired:
            self._states.pop(s, None)

    def clear(self) -> None:
        """Clear all states (useful for testing)."""
        self._states.clear()


# Global state manager singleton
_state_manager = OAuthStateManager()


def get_oauth_state_manager() -> OAuthStateManager:
    """Dependency provider for OAuthStateManager."""
    return _state_manager


# ═══════════════════════════════════════════════════════════════════════════
# 4. Google OAuth 2.0 Client
# ═══════════════════════════════════════════════════════════════════════════


class OAuthConfigProtocol(Protocol):
    client_id: Optional[str]
    client_secret: Optional[str]
    redirect_uri: str
    scopes: tuple[str, ...]

    def validate_oauth(self) -> bool: ...
    def is_oauth_configured(self) -> bool: ...


class GoogleOAuthClient:
    """Manages Google OAuth 2.0 authorization, code exchange, and token refresh."""

    def __init__(
        self,
        config: OAuthConfigProtocol,
        token_storage: Optional[BaseTokenStorage] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.config = config
        self.token_storage = token_storage or InMemoryTokenStorage()
        self._http_client = http_client

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=10.0)

    def get_authorization_url(
        self,
        state: Optional[str] = None,
        access_type: str = "offline",
        prompt: str = "consent",
    ) -> tuple[str, str]:
        """Generate Google OAuth 2.0 authorization URL.

        Args:
            state: Optional CSRF state token. Generated securely if omitted.
            access_type: 'offline' to receive a refresh token.
            prompt: 'consent' to force consent screen for offline access.

        Returns:
            Tuple of (authorization_url, state)
        """
        self.config.validate_oauth()
        generated_state = state or secrets.token_urlsafe(24)

        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.config.scopes),
            "access_type": access_type,
            "prompt": prompt,
            "state": generated_state,
        }
        url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
        return url, generated_state

    def exchange_code_for_token(
        self,
        code: str,
        state: Optional[str] = None,
        expected_state: Optional[str] = None,
    ) -> OAuthToken:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: The authorization code returned by Google.
            state: The state returned by Google callback.
            expected_state: The state previously generated during URL generation.

        Returns:
            OAuthToken instance saved to storage.

        Raises:
            OAuthAuthenticationError: If code exchange fails or state mismatches.
        """
        self.config.validate_oauth()

        if not code:
            raise OAuthAuthenticationError("Authorization code is empty or missing.")

        if expected_state and state != expected_state:
            raise OAuthAuthenticationError("OAuth state parameter mismatch (CSRF protection).")

        payload = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.config.redirect_uri,
        }

        try:
            client = self._get_http_client()
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            if response.status_code != 200:
                error_desc = self._extract_error_message(response)
                raise OAuthAuthenticationError(f"OAuth code exchange failed: {error_desc}")

            data = response.json()
            expires_in = data.get("expires_in")
            expires_at = time.time() + float(expires_in) if expires_in is not None else None

            token = OAuthToken(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                token_type=data.get("token_type", "Bearer"),
                expires_at=expires_at,
                scope=data.get("scope"),
            )
            self.token_storage.save_token(token)
            logger.info("Successfully obtained and saved new OAuth token.")
            return token

        except httpx.TimeoutException as exc:
            raise OAuthAuthenticationError("Network timeout during OAuth token exchange.") from exc
        except httpx.RequestError as exc:
            raise OAuthAuthenticationError(f"Network error during OAuth token exchange: {exc}") from exc

    def refresh_access_token(self) -> OAuthToken:
        """Use the refresh token to obtain a fresh access token.

        Returns:
            Updated OAuthToken instance.

        Raises:
            OAuthAuthenticationError: If refresh token is missing or rejected.
        """
        self.config.validate_oauth()

        current_token = self.token_storage.load_token()
        if not current_token or not current_token.refresh_token:
            raise OAuthAuthenticationError("No refresh token available to renew access.")

        payload = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": current_token.refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            client = self._get_http_client()
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            if response.status_code != 200:
                error_desc = self._extract_error_message(response)
                if response.status_code in (400, 401):
                    logger.warning(f"OAuth refresh token invalid or revoked ({response.status_code}). Clearing token from storage.")
                    self.token_storage.clear_token()
                raise OAuthAuthenticationError(f"Failed to refresh OAuth token: {error_desc}")

            data = response.json()
            expires_in = data.get("expires_in")
            expires_at = time.time() + float(expires_in) if expires_in is not None else None

            new_token = OAuthToken(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token") or current_token.refresh_token,
                token_type=data.get("token_type", current_token.token_type),
                expires_at=expires_at,
                scope=data.get("scope", current_token.scope),
            )
            self.token_storage.save_token(new_token)
            logger.info("Successfully refreshed OAuth access token.")
            return new_token

        except httpx.TimeoutException as exc:
            raise OAuthAuthenticationError("Network timeout during OAuth token refresh.") from exc
        except httpx.RequestError as exc:
            raise OAuthAuthenticationError(f"Network error during OAuth token refresh: {exc}") from exc

    def get_valid_access_token(self) -> str:
        """Return a guaranteed valid access token, refreshing if necessary.

        Returns:
            Valid access token string.

        Raises:
            OAuthConfigurationError: If OAuth credentials are missing.
            OAuthAuthenticationError: If token is missing, expired with no refresh, or refresh fails.
        """
        if not self.config.is_oauth_configured():
            raise OAuthConfigurationError("OAuth is not configured (missing client_id/client_secret).")

        token = self.token_storage.load_token()
        if not token:
            raise OAuthAuthenticationError(
                "OAuth not authorized: No token found. Please complete authorization flow."
            )

        if token.is_expired():
            if not token.has_refresh_token():
                raise OAuthAuthenticationError("OAuth access token expired and no refresh token is present.")
            token = self.refresh_access_token()

        return token.access_token

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        """Safely extract error message without leaking sensitive information."""
        try:
            err_data = response.json()
            error = err_data.get("error_description") or err_data.get("error") or response.text
            return str(error)
        except Exception:
            return f"HTTP {response.status_code}"
