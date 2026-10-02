"""Configuration dataclass and validation for Google Chat and OAuth 2.0."""

from dataclasses import dataclass, field
from typing import Any, Optional

from app.notifications.google_chat.exceptions import OAuthConfigurationError
from app.security.redaction import redact_string

DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/chat.messages.create",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
)
DEFAULT_REDIRECT_URI = "http://localhost:8000/api/auth/google-chat/callback"


@dataclass(frozen=True)
class GoogleChatConfig:
    """Immutable configuration for Google Chat notification provider.

    Safety:
    - Never stores credentials in code
    - Secret fields are redacted in repr and string output
    - Supports local-first storage and configuration
    """

    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    default_space: Optional[str] = None
    recipient_space_mapping: dict[str, str] = field(default_factory=dict)
    token_file: Optional[str] = None

    def is_oauth_configured(self) -> bool:
        """Return True if OAuth client credentials (client_id and client_secret) are present."""
        return bool(self.client_id and self.client_secret)

    def validate_oauth(self) -> bool:
        """Validate OAuth client credentials.

        Raises:
            OAuthConfigurationError: If client_id or client_secret are missing.
        """
        if not self.client_id:
            raise OAuthConfigurationError("Google Chat OAuth client_id is not configured.")
        if not self.client_secret:
            raise OAuthConfigurationError("Google Chat OAuth client_secret is not configured.")
        return True

    def validate_space_configuration(self) -> bool:
        """Validate that a default space or at least one recipient mapping is configured.

        Raises:
            OAuthConfigurationError: If no space or mapping is available.
        """
        if not self.default_space and not self.recipient_space_mapping:
            raise OAuthConfigurationError(
                "Neither default_space nor recipient_space_mapping is configured for Google Chat."
            )
        return True

    def safe_dict(self) -> dict[str, Any]:
        """Return dictionary representation with sensitive values masked."""
        return {
            "client_id": self.client_id,
            "client_secret": "[REDACTED]" if self.client_secret else None,
            "redirect_uri": self.redirect_uri,
            "scopes": list(self.scopes),
            "default_space": self.default_space,
            "recipient_space_mapping": self.recipient_space_mapping,
            "token_file": self.token_file,
            "is_oauth_configured": self.is_oauth_configured(),
        }

    def __repr__(self) -> str:
        secret_repr = "[REDACTED]" if self.client_secret else "None"
        return (
            f"GoogleChatConfig(client_id={self.client_id!r}, "
            f"client_secret={secret_repr}, "
            f"redirect_uri={self.redirect_uri!r}, "
            f"default_space={self.default_space!r})"
        )
