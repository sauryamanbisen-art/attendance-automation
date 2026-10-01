"""Production Google Chat notification provider implementing BaseNotificationProvider."""

import logging
from typing import Any, Optional

import httpx

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationOutcome,
    NotificationPayload,
)
from app.notifications.google_chat.client import GoogleChatClient
from app.notifications.google_chat.config import GoogleChatConfig
from app.notifications.google_chat.exceptions import (
    GoogleChatError,
    GoogleChatRecipientError,
    OAuthConfigurationError,
)
from app.notifications.google_chat.oauth import (
    BaseTokenStorage,
    FileTokenStorage,
    GoogleChatOAuthClient,
    InMemoryTokenStorage,
)
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)


class GoogleChatNotificationProvider(BaseNotificationProvider):
    """Official Google Chat notification provider using Google Chat REST API v1 and OAuth 2.0.

    Strict Architectural Invariants:
    - Pure transport layer: NEVER makes or overrides attendance eligibility decisions.
    - Only receives already-approved notification payloads from NotificationService.
    - Failures fail closed safely without affecting attendance or decision records.
    - Uses official Google Chat API with OAuth 2.0.
    - Never stores credentials in git; all secrets redacted in representations and logs.
    """

    def __init__(
        self,
        config: Optional[GoogleChatConfig] = None,
        oauth_client: Optional[GoogleChatOAuthClient] = None,
        api_client: Optional[GoogleChatClient] = None,
        token_storage: Optional[BaseTokenStorage] = None,
        http_client: Optional[httpx.Client] = None,
        is_dry_run: bool = False,
    ) -> None:
        self.config = config or GoogleChatConfig()
        self._is_dry_run = is_dry_run

        # Initialize token storage
        if token_storage is not None:
            self.token_storage = token_storage
        elif self.config.token_file:
            self.token_storage = FileTokenStorage(self.config.token_file)
        else:
            self.token_storage = InMemoryTokenStorage()

        # Initialize OAuth client
        self.oauth_client = oauth_client or GoogleChatOAuthClient(
            config=self.config,
            token_storage=self.token_storage,
            http_client=http_client,
        )

        # Initialize API client
        self.api_client = api_client or GoogleChatClient(
            oauth_client=self.oauth_client,
            http_client=http_client,
        )

    @property
    def provider_name(self) -> str:
        return "google_chat"

    @property
    def is_dry_run(self) -> bool:
        return self._is_dry_run

    def validate_config(self) -> bool:
        """Validate OAuth and routing configuration.

        Returns:
            True if configuration is complete and valid.

        Raises:
            OAuthConfigurationError: If configuration is invalid.
        """
        self.config.validate_oauth()
        self.config.validate_space_configuration()
        return True

    def resolve_space(self, payload: NotificationPayload) -> str:
        """Resolve the Google Chat space destination for this notification.

        Priority order:
        1. Payload metadata ("space_id" or "space")
        2. Recipient email mapping from configuration
        3. Configured default space

        Raises:
            GoogleChatRecipientError: If no valid space can be determined.
        """
        # 1. Payload metadata
        meta_space = payload.metadata.get("space_id") or payload.metadata.get("space")
        if meta_space and isinstance(meta_space, str) and meta_space.strip():
            return meta_space.strip()

        # 2. Recipient mapping
        recipient = payload.recipient_email.strip().lower()
        if recipient in self.config.recipient_space_mapping:
            mapped_space = self.config.recipient_space_mapping[recipient]
            if mapped_space and mapped_space.strip():
                return mapped_space.strip()

        # 3. Default space
        if self.config.default_space and self.config.default_space.strip():
            return self.config.default_space.strip()

        raise GoogleChatRecipientError(
            f"No Google Chat space configured for recipient '{payload.recipient_email}'."
        )

    def format_chat_message(self, payload: NotificationPayload) -> str:
        """Format the factual, polite notification for Google Chat display."""
        # Bold header followed by polite message body
        return f"*{payload.message_subject}*\n\n{payload.message_body}"

    def send(self, payload: NotificationPayload) -> NotificationOutcome:
        """Deliver an attendance review request message via Google Chat API.

        This method NEVER modifies attendance records or makes eligibility decisions.
        Failures return a failed NotificationOutcome for audit logging.

        Args:
            payload: Immutable notification payload.

        Returns:
            NotificationOutcome indicating success or failure.
        """
        message_text = self.format_chat_message(payload)
        preview = (
            f"PROVIDER: google_chat\n"
            f"TO: {payload.recipient_email}\n"
            f"SUBJECT: {payload.message_subject}\n"
            f"---\n{message_text}"
        )

        # 1. Validate recipient email format
        if not payload.recipient_email or "@" not in payload.recipient_email:
            err_msg = f"Invalid recipient email: '{payload.recipient_email}'."
            logger.warning("Google Chat send failed: %s", err_msg)
            return NotificationOutcome(
                success=False,
                provider_name=self.provider_name,
                is_dry_run=self.is_dry_run,
                message_preview=preview,
                error_message=err_msg,
                details={"recipient": payload.recipient_email},
            )

        # 2. Resolve destination space
        try:
            target_space = self.resolve_space(payload)
        except GoogleChatRecipientError as exc:
            logger.warning("Google Chat space resolution failed: %s", exc)
            return NotificationOutcome(
                success=False,
                provider_name=self.provider_name,
                is_dry_run=self.is_dry_run,
                message_preview=preview,
                error_message=str(exc),
                details={"recipient": payload.recipient_email},
            )

        # 3. Dry run guard: NEVER make external requests
        if self.is_dry_run:
            logger.info(
                "[DRY RUN] Would have dispatched Google Chat message to %s in space %s",
                payload.recipient_email,
                target_space,
            )
            return NotificationOutcome(
                success=True,
                provider_name=self.provider_name,
                is_dry_run=True,
                message_preview=preview,
                error_message=None,
                details={
                    "recipient": payload.recipient_email,
                    "space": target_space,
                    "subject_code": payload.subject_code,
                    "target_date": payload.target_date.isoformat(),
                },
            )

        # 4. Deliver message via Google Chat API
        try:
            api_response = self.api_client.send_message(
                space_name=target_space,
                text=message_text,
            )
            message_name = api_response.get("name", "unknown")
            logger.info(
                "Successfully dispatched Google Chat notification to %s in space %s (msg: %s)",
                payload.recipient_email,
                target_space,
                message_name,
            )
            return NotificationOutcome(
                success=True,
                provider_name=self.provider_name,
                is_dry_run=False,
                message_preview=preview,
                error_message=None,
                details={
                    "recipient": payload.recipient_email,
                    "space": target_space,
                    "message_id": message_name,
                    "subject_code": payload.subject_code,
                    "target_date": payload.target_date.isoformat(),
                },
            )

        except GoogleChatError as exc:
            safe_error = redact_string(str(exc))
            logger.error("Google Chat delivery failed for %s: %s", payload.recipient_email, safe_error)
            return NotificationOutcome(
                success=False,
                provider_name=self.provider_name,
                is_dry_run=False,
                message_preview=preview,
                error_message=safe_error,
                details={
                    "recipient": payload.recipient_email,
                    "space": target_space,
                    "error_type": type(exc).__name__,
                },
            )
        except Exception as exc:
            safe_error = redact_string(str(exc))
            logger.error("Unexpected error in Google Chat provider for %s: %s", payload.recipient_email, safe_error)
            return NotificationOutcome(
                success=False,
                provider_name=self.provider_name,
                is_dry_run=False,
                message_preview=preview,
                error_message=f"Unexpected error: {safe_error}",
                details={
                    "recipient": payload.recipient_email,
                    "space": target_space,
                    "error_type": type(exc).__name__,
                },
            )
