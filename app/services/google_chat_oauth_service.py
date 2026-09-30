"""Service layer for Google Chat OAuth 2.0 and space routing management.

Safety Guarantees:
- CSRF protection via cryptographically generated state with time-to-live expiration.
- Secrets (client_secret, access_token, refresh_token, code) are NEVER leaked.
- Token storage strictly isolated to local-first secure storage.
- Fails closed safely if credentials are not configured or invalid.
"""

import logging
import os
import secrets
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.professor_mapping import ProfessorMapping
from app.models.setting import Setting
from app.models.subject import Subject
from app.notifications.google_chat.config import GoogleChatConfig
from app.notifications.google_chat.exceptions import (
    OAuthAuthenticationError,
    OAuthConfigurationError,
)
from app.notifications.google_chat.oauth import (
    BaseTokenStorage,
    FileTokenStorage,
    GoogleChatOAuthClient,
    InMemoryTokenStorage,
    OAuthToken,
)
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_FILE = "credentials/google_chat_token.json"


from app.notifications.oauth import OAuthStateManager, get_oauth_state_manager

_state_manager = get_oauth_state_manager()




class GoogleChatOAuthService:
    """Service mediating OAuth operations between FastAPI routes and Google Chat client."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        token_storage: Optional[BaseTokenStorage] = None,
        oauth_client: Optional[GoogleChatOAuthClient] = None,
        state_manager: Optional[OAuthStateManager] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.state_manager = state_manager or _state_manager

        # Token storage: custom > configured token file > default file
        if token_storage is not None:
            self.token_storage = token_storage
        else:
            token_file = self.settings.google_chat_token_file or DEFAULT_TOKEN_FILE
            self.token_storage = FileTokenStorage(token_file)

        # OAuth client
        if oauth_client is not None:
            self.oauth_client = oauth_client
        else:
            config = self._build_config()
            self.oauth_client = GoogleChatOAuthClient(
                config=config,
                token_storage=self.token_storage,
            )

    def _build_config(self, default_space: Optional[str] = None) -> GoogleChatConfig:
        """Construct GoogleChatConfig from application settings."""
        token_file = self.settings.google_chat_token_file or DEFAULT_TOKEN_FILE
        return GoogleChatConfig(
            client_id=self.settings.google_chat_client_id,
            client_secret=self.settings.google_chat_client_secret,
            redirect_uri=self.settings.google_chat_redirect_uri,
            default_space=default_space or self.settings.google_chat_default_space,
            token_file=token_file,
        )

    def is_configured(self) -> bool:
        """Return True if OAuth client credentials (client_id and client_secret) are set."""
        return bool(self.settings.google_chat_client_id and self.settings.google_chat_client_secret)

    def get_authorization_url(self, prompt: str = "consent") -> tuple[str, str]:
        """Generate Google OAuth authorization URL with fresh CSRF state.

        Raises:
            OAuthConfigurationError: If client_id or client_secret are not configured.
        """
        if not self.is_configured():
            raise OAuthConfigurationError(
                "Google Chat OAuth is not configured. Please set GOOGLE_CHAT_CLIENT_ID "
                "and GOOGLE_CHAT_CLIENT_SECRET in your environment or .env file."
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
            logger.warning("Google Chat OAuth callback received error: %s", safe_desc)
            raise OAuthAuthenticationError(f"OAuth authorization denied or cancelled by user: {safe_desc}")

        if not state or not self.state_manager.validate_and_consume(state):
            logger.warning("Google Chat OAuth callback received invalid or expired state token.")
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
        """Get sanitized, unexposed connection and configuration status."""
        configured = self.is_configured()
        token = self.token_storage.load_token()

        connected = False
        is_expired = False
        has_refresh_token = False
        expires_at = None
        scopes = list(self.oauth_client.config.scopes)

        if token:
            has_refresh_token = token.has_refresh_token()
            is_expired = token.is_expired()
            expires_at = token.expires_at
            # Connected if token is currently valid OR can be refreshed
            connected = not is_expired or has_refresh_token

        # Resolve default space (database override or settings fallback)
        default_space = self.get_effective_default_space(db)

        # Count configured professor spaces in DB
        recipient_mappings_count = 0
        if db is not None:
            recipient_mappings_count = (
                db.query(ProfessorMapping)
                .filter(
                    ProfessorMapping.google_chat_space.isnot(None),
                    ProfessorMapping.google_chat_space != "",
                )
                .count()
            )

        return {
            "configured": configured,
            "connected": connected,
            "is_expired": is_expired,
            "has_refresh_token": has_refresh_token,
            "expires_at": expires_at,
            "default_space": default_space,
            "scopes": scopes,
            "dry_run": self.settings.dry_run,
            "recipient_mappings_count": recipient_mappings_count,
            "client_id_configured": bool(self.settings.google_chat_client_id),
        }

    def disconnect(self) -> None:
        """Revoke local authorization credentials by clearing token storage."""
        self.token_storage.clear_token()
        logger.info("Cleared local Google Chat OAuth tokens.")

    def get_effective_default_space(self, db: Optional[Session] = None) -> Optional[str]:
        """Retrieve default space from DB setting if configured, else from app settings."""
        if db is not None:
            setting = db.query(Setting).filter(Setting.key == "google_chat_default_space").first()
            if setting and setting.value and setting.value.strip():
                return setting.value.strip()
        return self.settings.google_chat_default_space

    def set_default_space(self, db: Session, default_space: Optional[str]) -> Optional[str]:
        """Persist or clear the default Google Chat fallback space in database."""
        val = default_space.strip() if default_space and default_space.strip() else ""
        setting = db.query(Setting).filter(Setting.key == "google_chat_default_space").first()
        if setting:
            setting.value = val
        else:
            setting = Setting(
                key="google_chat_default_space",
                value=val,
                description="Default Google Chat space fallback",
            )
            db.add(setting)
        db.commit()
        return val or None

    def get_professor_spaces(self, db: Session) -> list[dict[str, Any]]:
        """List all registered subjects and their professor space mapping."""
        subjects = db.query(Subject).all()
        items = []
        for s in subjects:
            prof_name = s.professor_mapping.professor_name if s.professor_mapping else None
            prof_email = s.professor_mapping.professor_email if s.professor_mapping else None
            space = s.professor_mapping.google_chat_space if s.professor_mapping else None
            items.append(
                {
                    "subject_code": s.code,
                    "subject_name": s.name,
                    "professor_name": prof_name,
                    "professor_email": prof_email,
                    "google_chat_space": space,
                    "is_configured": bool(space and space.strip()),
                }
            )
        return items

    def update_professor_space(
        self,
        db: Session,
        subject_code: str,
        google_chat_space: Optional[str],
    ) -> dict[str, Any]:
        """Update or clear the Google Chat space for a specific subject's professor."""
        subject = db.query(Subject).filter(Subject.code == subject_code).first()
        if not subject:
            raise KeyError(f"Subject '{subject_code}' not found.")

        if not subject.professor_mapping:
            raise ValueError(f"Subject '{subject_code}' does not have a professor assigned yet.")

        cleaned_space = google_chat_space.strip() if google_chat_space and google_chat_space.strip() else None
        subject.professor_mapping.google_chat_space = cleaned_space
        db.commit()
        db.refresh(subject.professor_mapping)

        return {
            "subject_code": subject.code,
            "subject_name": subject.name,
            "professor_name": subject.professor_mapping.professor_name,
            "professor_email": subject.professor_mapping.professor_email,
            "google_chat_space": subject.professor_mapping.google_chat_space,
            "is_configured": bool(subject.professor_mapping.google_chat_space),
        }
