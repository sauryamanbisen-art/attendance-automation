"""Gmail notification provider implementation."""

import logging
from typing import Any, Optional

import httpx

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationConfigError,
    NotificationDeliveryError,
    NotificationOutcome,
    NotificationPayload,
    NotificationProviderError,
)
from app.notifications.gmail.client import GmailClient
from app.notifications.gmail.config import GmailConfig
from app.notifications.oauth import (
    BaseTokenStorage,
    FileTokenStorage,
    GoogleOAuthClient,
    InMemoryTokenStorage,
)
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)


class GmailNotificationProvider(BaseNotificationProvider):
    """Notification provider that dispatches messages via Gmail API.

    Strict Architectural Invariants:
    - Pure transport layer: NEVER makes or overrides attendance eligibility decisions.
    - Only receives already-approved notification payloads from NotificationService.
    - Failures fail closed safely without affecting attendance or decision records.
    - Uses official Gmail API with OAuth 2.0.
    - Never stores credentials in git; all secrets redacted in representations and logs.
    """

    def __init__(
        self,
        client: Optional[GmailClient] = None,
        config: Optional[GmailConfig] = None,
        oauth_client: Optional[GoogleOAuthClient] = None,
        token_storage: Optional[BaseTokenStorage] = None,
        http_client: Optional[httpx.Client] = None,
        is_dry_run: bool = False,
    ) -> None:
        self._is_dry_run = is_dry_run

        if client is not None:
            self.client = client
            self.config = getattr(client, "config", config or GmailConfig())
            self.oauth_client = getattr(client, "oauth_client", None)
            self.token_storage = getattr(self.oauth_client, "token_storage", None) if self.oauth_client else None
        else:
            self.config = config or GmailConfig()
            if token_storage is not None:
                self.token_storage = token_storage
            elif self.config.token_file:
                self.token_storage = FileTokenStorage(self.config.token_file)
            else:
                self.token_storage = InMemoryTokenStorage()

            self.oauth_client = oauth_client or GoogleOAuthClient(
                config=self.config,
                token_storage=self.token_storage,
                http_client=http_client,
            )
            self.client = GmailClient(
                config=self.config,
                oauth_client=self.oauth_client,
                http_client=http_client,
            )

    @property
    def provider_name(self) -> str:
        return "gmail"

    @property
    def is_dry_run(self) -> bool:
        return self._is_dry_run

    def format_email_preview(self, payload: NotificationPayload) -> str:
        """Format a preview representation of the email for audit logging."""
        return (
            f"PROVIDER: gmail\n"
            f"TO: {payload.recipient_email}\n"
            f"SUBJECT: {payload.message_subject}\n"
            f"---\n{payload.message_body}"
        )

    def send(self, payload: NotificationPayload) -> NotificationOutcome:
        """Send notification via Gmail.

        Args:
            payload: The notification payload to dispatch.

        Returns:
            NotificationOutcome detailing success/failure.

        Raises:
            NotificationDeliveryError: If the Gmail API fails.
        """
        logger.info(
            "Dispatching Gmail notification to %s for %s (%s)",
            payload.recipient_email,
            payload.subject_code,
            payload.target_date,
        )

        preview = self.format_email_preview(payload)

        # Dry run guard: NEVER make external requests
        if self.is_dry_run:
            logger.info("[DRY RUN] Would have sent Gmail to %s", payload.recipient_email)
            return NotificationOutcome(
                success=True,
                provider_name=self.provider_name,
                is_dry_run=True,
                message_preview=preview,
                details={
                    "recipient": payload.recipient_email,
                    "subject_code": payload.subject_code,
                    "target_date": payload.target_date.isoformat(),
                },
            )

        # Validate recipient email format
        if not payload.recipient_email or "@" not in payload.recipient_email:
            err_msg = f"Invalid recipient email: '{payload.recipient_email}'."
            logger.warning("Gmail send failed: %s", err_msg)
            raise NotificationDeliveryError(err_msg)

        try:
            result = self.client.send_email(
                recipient_email=payload.recipient_email,
                subject=payload.message_subject,
                body=payload.message_body,
            )
            return NotificationOutcome(
                success=True,
                provider_name=self.provider_name,
                is_dry_run=False,
                message_preview=preview,
                details={"external_id": result.get("id")} if result.get("id") else {},
            )
        except NotificationProviderError as exc:
            safe_error = redact_string(str(exc))
            logger.error("Gmail notification failed for %s: %s", payload.recipient_email, safe_error)
            raise NotificationDeliveryError(f"Gmail failed to deliver message: {safe_error}") from exc
        except Exception as exc:
            safe_error = redact_string(str(exc))
            logger.error("Unexpected error in Gmail notification provider: %s", safe_error)
            raise NotificationDeliveryError(f"Gmail unexpected failure: {safe_error}") from exc

    def validate_config(self) -> bool:
        """Validate that this provider's configuration is correct."""
        try:
            self.config.validate_oauth()
            return True
        except Exception as exc:
            raise NotificationConfigError(f"Gmail config invalid: {exc}") from exc
