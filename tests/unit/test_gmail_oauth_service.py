import os
import stat
import tempfile
import time
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.notifications.oauth import (
    FileTokenStorage,
    InMemoryTokenStorage,
    OAuthAuthenticationError,
    OAuthConfigurationError,
    OAuthStateManager,
    OAuthToken,
)
from app.services.gmail_oauth_service import GmailOAuthService


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gmail_client_id="test_client",
        gmail_client_secret="test_secret",
        gmail_redirect_uri="http://localhost:8000/callback",
        notification_sender_email="student@university.edu",
    )


@pytest.fixture
def state_manager() -> OAuthStateManager:
    return OAuthStateManager()


@pytest.fixture
def token_storage() -> InMemoryTokenStorage:
    return InMemoryTokenStorage()


@pytest.fixture
def service(
    settings: Settings,
    state_manager: OAuthStateManager,
    token_storage: InMemoryTokenStorage,
) -> GmailOAuthService:
    return GmailOAuthService(
        settings=settings,
        token_storage=token_storage,
        state_manager=state_manager,
    )


def test_get_authorization_url(service: GmailOAuthService):
    url, state = service.get_authorization_url()

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test_client" in url
    assert f"state={state}" in url

    # State should be tracked
    assert service.state_manager.validate_and_consume(state) is True


def test_missing_config(service: GmailOAuthService):
    service.settings.gmail_client_id = None

    with pytest.raises(OAuthConfigurationError):
        service.get_authorization_url()


def test_handle_callback_error(service: GmailOAuthService):
    with pytest.raises(OAuthAuthenticationError, match="denied"):
        service.handle_callback(code=None, state="123", error="access_denied")


def test_handle_callback_invalid_state(service: GmailOAuthService):
    with pytest.raises(OAuthAuthenticationError, match="Invalid or expired"):
        service.handle_callback(code="auth_code", state="invalid_state")


def test_handle_callback_missing_code(service: GmailOAuthService):
    state = service.state_manager.generate_state()
    with pytest.raises(OAuthAuthenticationError, match="code is missing"):
        service.handle_callback(code=None, state=state)


def test_connection_status(service: GmailOAuthService, token_storage: InMemoryTokenStorage):
    # Connected should be false initially
    status = service.get_connection_status()
    assert status["configured"] is True
    assert status["connected"] is False
    assert status["token_exists"] is False

    # Store token
    token = OAuthToken(access_token="mock_token", expires_at=time.time() + 3600.0)  # valid
    token_storage.save_token(token)

    status2 = service.get_connection_status()
    assert status2["token_exists"] is True
    assert status2["connected"] is True
    assert status2["is_expired"] is False


def test_connection_status_expired_handling(service: GmailOAuthService, token_storage: InMemoryTokenStorage):
    # Expired token with refresh token -> still considered connected
    token_with_refresh = OAuthToken(
        access_token="old_token",
        refresh_token="ref_tok",
        expires_at=time.time() - 100,
    )
    token_storage.save_token(token_with_refresh)
    s1 = service.get_connection_status()
    assert s1["is_expired"] is True
    assert s1["has_refresh_token"] is True
    assert s1["connected"] is True

    # Expired token without refresh token -> not connected
    token_no_refresh = OAuthToken(
        access_token="old_token",
        refresh_token=None,
        expires_at=time.time() - 100,
    )
    token_storage.save_token(token_no_refresh)
    s2 = service.get_connection_status()
    assert s2["is_expired"] is True
    assert s2["has_refresh_token"] is False
    assert s2["connected"] is False


def test_connection_status_does_not_expose_secrets(service: GmailOAuthService, token_storage: InMemoryTokenStorage):
    token = OAuthToken(
        access_token="secret_access_xyz",
        refresh_token="secret_refresh_abc",
        expires_at=time.time() + 3600,
    )
    token_storage.save_token(token)
    status = service.get_connection_status()

    status_str = str(status)
    assert "secret_access_xyz" not in status_str
    assert "secret_refresh_abc" not in status_str
    assert "test_secret" not in status_str


def test_disconnect(service: GmailOAuthService, token_storage: InMemoryTokenStorage):
    token = OAuthToken(access_token="mock_token", expires_at=2000000000.0)
    token_storage.save_token(token)

    assert token_storage.load_token() is not None

    service.disconnect()

    assert token_storage.load_token() is None


def test_file_token_storage_lifecycle_and_permissions():
    """Verify FileTokenStorage saves with POSIX 0600 permissions, loads, and clears."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = os.path.join(tmpdir, "subdir", "gmail_token.json")
        storage = FileTokenStorage(token_path)

        assert storage.load_token() is None

        test_token = OAuthToken(
            access_token="ya29.sample_token_val",
            refresh_token="1//sample_ref",
            expires_at=time.time() + 1800,
            scope="https://www.googleapis.com/auth/gmail.send",
        )
        storage.save_token(test_token)

        assert os.path.exists(token_path)
        # Verify file permission is 0600 on POSIX platforms
        if hasattr(os, "stat"):
            file_mode = stat.S_IMODE(os.stat(token_path).st_mode)
            assert file_mode == 0o600

        # Reload
        loaded = storage.load_token()
        assert loaded is not None
        assert loaded.access_token == "ya29.sample_token_val"
        assert loaded.refresh_token == "1//sample_ref"

        # Clear
        storage.clear_token()
        assert not os.path.exists(token_path)
        assert storage.load_token() is None
