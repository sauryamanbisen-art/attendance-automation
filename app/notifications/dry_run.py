"""Dry-run notification provider — logs messages without any network requests.

This provider NEVER makes HTTP calls, sends emails, or interacts with external
services. It is the default safe provider during development and testing.
"""

import logging
from typing import Any

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationOutcome,
    NotificationPayload,
)

logger = logging.getLogger(__name__)


class DryRunNotificationProvider(BaseNotificationProvider):
    """Notification provider that logs messages locally without sending anything.

    Safety guarantees:
    - NEVER makes network requests (HTTP, SMTP, WebSocket, or otherwise)
    - NEVER imports networking libraries (requests, httpx, smtplib, etc.)
    - NEVER opens sockets or file handles to external services
    - ALWAYS returns a successful NotificationOutcome with is_dry_run=True
    - ALWAYS logs the full message preview for audit/debugging purposes

    This provider is suitable for:
    - Local development and testing
    - CI/CD pipeline runs
    - Verifying message content before enabling a real provider
    """

    @property
    def provider_name(self) -> str:
        return "dry_run"

    @property
    def is_dry_run(self) -> bool:
        return True

    def send(self, payload: NotificationPayload) -> NotificationOutcome:
        """Log the notification payload locally and return a dry-run outcome.

        This method will NEVER send any external network request.

        Args:
            payload: The notification payload to "send" (log only).

        Returns:
            NotificationOutcome with success=True, is_dry_run=True.
        """
        preview = self._format_preview(payload)

        logger.info(
            "[DRY RUN] Notification would be sent:\n"
            "  To: %s\n"
            "  Subject: %s\n"
            "  Date: %s\n"
            "  Course: %s (%s)\n"
            "---\n%s\n---",
            payload.recipient_email,
            payload.message_subject,
            payload.target_date.isoformat(),
            payload.subject_name,
            payload.subject_code,
            payload.message_body,
        )

        return NotificationOutcome(
            success=True,
            provider_name=self.provider_name,
            is_dry_run=True,
            message_preview=preview,
            error_message=None,
            details={
                "recipient": payload.recipient_email,
                "subject_code": payload.subject_code,
                "target_date": payload.target_date.isoformat(),
            },
        )

    def validate_config(self) -> bool:
        """Dry-run provider requires no configuration.

        Returns:
            Always True — no external config needed.
        """
        return True

    @staticmethod
    def _format_preview(payload: NotificationPayload) -> str:
        """Create a human-readable preview of the notification for logging/audit."""
        return (
            f"TO: {payload.recipient_email}\n"
            f"SUBJECT: {payload.message_subject}\n"
            f"DATE: {payload.target_date.isoformat()}\n"
            f"COURSE: {payload.subject_name} ({payload.subject_code})\n"
            f"\n"
            f"{payload.message_body}"
        )
