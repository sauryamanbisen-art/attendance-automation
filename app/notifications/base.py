"""Abstract base class and contract for notification providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass(frozen=True)
class NotificationPayload:
    """Immutable payload passed to a notification provider.

    This dataclass carries everything a provider needs to deliver a notification.
    Providers must NOT make eligibility decisions — they only transmit the message.
    """

    subject_code: str
    subject_name: str
    target_date: date
    recipient_email: str
    professor_name: str
    message_subject: str
    message_body: str
    student_name: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationOutcome:
    """Result of a notification send attempt.

    Providers return this to indicate success, failure, or dry-run skip.
    """

    success: bool
    provider_name: str
    is_dry_run: bool
    message_preview: str
    error_message: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


class BaseNotificationProvider(ABC):
    """Contract that every notification provider must implement.

    Providers are pure delivery mechanisms. They MUST NOT:
    - Make attendance eligibility decisions
    - Query the database for attendance or confirmation data
    - Override the decision engine's verdict

    The NotificationService is responsible for filtering eligible records
    before dispatching to a provider.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique name identifying this provider (e.g. 'dry_run', 'google_chat')."""
        ...

    @property
    @abstractmethod
    def is_dry_run(self) -> bool:
        """True if this provider never makes real external requests."""
        ...

    @abstractmethod
    def send(self, payload: NotificationPayload) -> NotificationOutcome:
        """Deliver a notification using this provider's transport.

        Args:
            payload: Immutable notification payload with message and recipient info.

        Returns:
            NotificationOutcome describing what happened.
        """
        ...

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate that this provider's configuration is correct.

        Returns:
            True if configuration is valid and the provider can operate.

        Raises:
            NotificationConfigError: If configuration is invalid.
        """
        ...


class NotificationProviderError(Exception):
    """Base exception for notification provider failures."""

    pass


class NotificationConfigError(NotificationProviderError):
    """Raised when provider configuration is invalid or incomplete."""

    pass


class NotificationDeliveryError(NotificationProviderError):
    """Raised when a notification fails to deliver after provider-level retry."""

    pass
