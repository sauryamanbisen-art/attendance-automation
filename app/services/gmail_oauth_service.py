"""Service mediating OAuth operations between FastAPI routes and Gmail client."""

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.notifications.gmail.config import GmailConfig
from app.notifications.oauth import (
    BaseTokenStorage,
    FileTokenStorage,
    GoogleOAuthClient,
    OAuthAuthenticationError,
    OAuthConfigurationError,
    OAuthStateManager,
    OAuthToken,
    get_oauth_state_manager,
)
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_FILE = "credentials/gmail_token.json"


class GmailOAuthService:
    """Service mediating OAuth operations between FastAPI routes and Gmail client."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        token_storage: Optional[BaseTokenStorage] = None,
        oauth_client: Optional[GoogleOAuthClient] = None,
        state_manager: Optional[OAuthStateManager] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.state_manager = state_manager or get_oauth_state_manager()

        # Token storage: custom > configured token file > default file
        if token_storage is not None:
            self.token_storage = token_storage
        else:
            token_file = self.settings.gmail_token_file or DEFAULT_TOKEN_FILE
            self.token_storage = FileTokenStorage(token_file)

        # OAuth client
        if oauth_client is not None:
            self.oauth_client = oauth_client
        else:
            config = self._build_config()
            self.oauth_client = GoogleOAuthClient(
                config=config,
                token_storage=self.token_storage,
            )

    def _build_config(self) -> GmailConfig:
        """Construct GmailConfig from application settings."""
        token_file = self.settings.gmail_token_file or DEFAULT_TOKEN_FILE
        return GmailConfig(
            client_id=self.settings.gmail_client_id,
            client_secret=self.settings.gmail_client_secret,
            redirect_uri=self.settings.gmail_redirect_uri,
            token_file=token_file,
            sender_email=self.settings.notification_sender_email,
        )

    def is_configured(self) -> bool:
        """Return True if OAuth client credentials (client_id and client_secret) are set."""
        return bool(self.settings.gmail_client_id and self.settings.gmail_client_secret)

    def get_authorization_url(self, prompt: str = "consent") -> tuple[str, str]:
        """Generate Google OAuth authorization URL with fresh CSRF state.

        Raises:
            OAuthConfigurationError: If client_id or client_secret are not configured.
        """
        if not self.is_configured():
            raise OAuthConfigurationError(
                "Gmail OAuth is not configured. Please set GMAIL_CLIENT_ID "
                "and GMAIL_CLIENT_SECRET in your environment or .env file."
            )

        state = self.state_manager.generate_state()
        url, _ = self.oauth_client.get_authorization_url(
            state=state,
            access_type="offline",
            prompt=prompt,
        )
        return url, state

    def handle_callback(
        self,
        code: Optional[str],
        state: Optional[str],
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ) -> OAuthToken:
        """Validate CSRF state and exchange authorization code for tokens.

        Raises:
            OAuthAuthenticationError: If state is invalid, authorization denied, or code exchange fails.
            OAuthConfigurationError: If OAuth credentials are missing.
        """
        if error:
            safe_desc = redact_string(error_description or error)
            logger.warning("Gmail OAuth callback received error: %s", safe_desc)
            raise OAuthAuthenticationError(f"OAuth authorization denied or cancelled by user: {safe_desc}")

        if not state or not self.state_manager.validate_and_consume(state):
            logger.warning("Gmail OAuth callback received invalid or expired state token.")
            raise OAuthAuthenticationError("Invalid or expired OAuth state parameter (CSRF protection).")

        if not code:
            raise OAuthAuthenticationError("Authorization code is missing from OAuth callback.")

        # Exchange code for token
        return self.oauth_client.exchange_code_for_token(
            code=code,
            state=state,
            expected_state=state,
        )

    def get_connection_status(self, db: Optional[Session] = None) -> dict[str, Any]:
        """Return a safe dictionary of connection status for API consumption."""
        configured = self.is_configured()
        token = self.token_storage.load_token()

        connected = False
        is_expired = False
        has_refresh_token = False
        expires_at = None
        scopes = list(self.oauth_client.config.scopes)
        token_exists = False

        if token:
            token_exists = True
            has_refresh_token = token.has_refresh_token()
            is_expired = token.is_expired()
            expires_at = token.expires_at
            # Connected if token is currently valid OR can be refreshed
            connected = not is_expired or has_refresh_token

        return {
            "configured": configured,
            "connected": connected,
            "is_expired": is_expired,
            "has_refresh_token": has_refresh_token,
            "expires_at": expires_at,
            "scopes": scopes,
            "dry_run": self.settings.dry_run,
            "client_id_configured": bool(self.settings.gmail_client_id),
            "token_exists": token_exists,
        }

    def disconnect(self) -> None:
        """Remove local authorization token."""
        self.token_storage.clear_token()
        logger.info("Gmail OAuth local token cleared.")
