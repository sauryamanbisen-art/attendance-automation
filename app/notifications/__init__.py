"""Notification provider abstraction layer.

Public API:
- BaseNotificationProvider: Abstract interface for notification providers
- DryRunNotificationProvider: Safe dry-run provider (no network requests)
- NotificationService: Orchestrator that dispatches eligible decisions
- NotificationPayload / NotificationOutcome: Data contracts
- Message generation utilities
"""

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationConfigError,
    NotificationDeliveryError,
    NotificationOutcome,
    NotificationPayload,
    NotificationProviderError,
)
from app.notifications.dry_run import DryRunNotificationProvider
from app.notifications.gmail import (
    GmailClient,
    GmailConfig,
    GmailNotificationProvider,
)
from app.notifications.google_chat import (
    GoogleChatClient,
    GoogleChatConfig,
    GoogleChatNotificationProvider,
    GoogleChatOAuthClient,
    OAuthToken,
)
from app.notifications.message import generate_correction_body, generate_correction_subject
from app.notifications.service import NotificationService

__all__ = [
    "BaseNotificationProvider",
    "DryRunNotificationProvider",
    "GmailClient",
    "GmailConfig",
    "GmailNotificationProvider",
    "GoogleChatClient",
    "GoogleChatConfig",
    "GoogleChatNotificationProvider",
    "GoogleChatOAuthClient",
    "NotificationConfigError",
    "NotificationDeliveryError",
    "NotificationOutcome",
    "NotificationPayload",
    "NotificationProviderError",
    "NotificationService",
    "OAuthToken",
    "generate_correction_body",
    "generate_correction_subject",
]

