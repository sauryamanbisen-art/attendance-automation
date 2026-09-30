"""Domain exceptions for Google Chat notification provider and OAuth."""

from app.notifications.base import (
    NotificationDeliveryError,
    NotificationProviderError,
)
from app.notifications.oauth import (
    OAuthAuthenticationError,
    OAuthConfigurationError,
    OAuthError,
)


class GoogleChatError(NotificationProviderError):
    """Base exception for all Google Chat provider errors."""

    pass


class GoogleChatPermissionError(GoogleChatError, NotificationDeliveryError):
    """Raised when Google Chat API returns 403 Forbidden (e.g. not in space or lacks scopes)."""

    pass


class GoogleChatRecipientError(GoogleChatError, NotificationDeliveryError):
    """Raised when the recipient or space cannot be found or is unsupported."""

    pass


class GoogleChatRateLimitError(GoogleChatError, NotificationDeliveryError):
    """Raised when Google Chat API returns 429 Too Many Requests / RESOURCE_EXHAUSTED."""

    pass


class GoogleChatApiError(GoogleChatError, NotificationDeliveryError):
    """Raised when Google Chat API returns an unexpected error or server failure (5xx)."""

    pass


__all__ = [
    "GoogleChatApiError",
    "GoogleChatError",
    "GoogleChatPermissionError",
    "GoogleChatRateLimitError",
    "GoogleChatRecipientError",
    "OAuthAuthenticationError",
    "OAuthConfigurationError",
    "OAuthError",
]
