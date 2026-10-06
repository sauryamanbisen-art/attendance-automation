"""Configuration dataclass and validation for Gmail and OAuth 2.0."""

from dataclasses import dataclass, field
from typing import Any, Optional

from app.notifications.oauth import OAuthConfigurationError
from app.security.redaction import redact_string

DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
)
DEFAULT_REDIRECT_URI = "http://localhost:8000/api/auth/gmail/callback"


@dataclass(frozen=True)
class GmailConfig:
    """Immutable configuration for Gmail notification provider."""

    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    token_file: Optional[str] = None
    sender_email: Optional[str] = None

    def is_oauth_configured(self) -> bool:
        """Return True if OAuth client credentials are present."""
        return bool(self.client_id and self.client_secret)

    def validate_oauth(self) -> bool:
        """Validate OAuth client credentials.

        Raises:
            OAuthConfigurationError: If client_id or client_secret are missing.
        """
        if not self.client_id:
            raise OAuthConfigurationError("Gmail OAuth client_id is not configured.")
        if not self.client_secret:
            raise OAuthConfigurationError("Gmail OAuth client_secret is not configured.")
        return True

    def safe_dict(self) -> dict[str, Any]:
        """Return dictionary representation with sensitive values masked."""
        return {
            "client_id": self.client_id,
            "client_secret": "[REDACTED]" if self.client_secret else None,
            "redirect_uri": self.redirect_uri,
            "scopes": list(self.scopes),
            "token_file": self.token_file,
            "sender_email": self.sender_email,
            "is_oauth_configured": self.is_oauth_configured(),
        }

    def __repr__(self) -> str:
        secret_repr = "[REDACTED]" if self.client_secret else "None"
        return (
            f"GmailConfig(client_id={self.client_id!r}, "
            f"client_secret={secret_repr}, "
            f"redirect_uri={self.redirect_uri!r}, "
            f"sender_email={self.sender_email!r})"
        )
