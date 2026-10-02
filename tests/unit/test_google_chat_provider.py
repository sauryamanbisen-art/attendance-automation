"""Comprehensive unit tests for the Google Chat notification provider and OAuth architecture.

Test categories:
1. GoogleChatConfig validation and secret redaction
2. OAuthToken lifecycle, expiration, and credential masking
3. Token storage implementations (InMemory and secure File)
4. GoogleChatOAuthClient (auth URL, code exchange, token refresh, error mapping)
5. GoogleChatClient (HTTP operations, headers, space normalization, API error status mapping)
6. GoogleChatNotificationProvider (resolution, formatting, delivery, fail-safe outcomes)
7. NotificationService integration & safety invariants
8. Structural network safety (no real network calls permitted)
"""

import ast
import inspect
import json
import os
import socket
import stat
import time
from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.enums import (
    AttendanceStatus,
    AuditEventType,
    DecisionAction,
    DecisionReason,
    NotificationStatus,
)
from app.database.base import Base
from app.models.audit_event import AuditEvent
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.base import (
    BaseNotificationProvider,
    NotificationOutcome,
    NotificationPayload,
)
from app.notifications.dry_run import DryRunNotificationProvider
from app.notifications.google_chat.client import GoogleChatClient
from app.notifications.google_chat.config import GoogleChatConfig
from app.notifications.google_chat.exceptions import (
    GoogleChatApiError,
    GoogleChatError,
    GoogleChatPermissionError,
    GoogleChatRateLimitError,
    GoogleChatRecipientError,
    OAuthAuthenticationError,
    OAuthConfigurationError,
)
from app.notifications.google_chat.oauth import (
    FileTokenStorage,
    GoogleChatOAuthClient,
    InMemoryTokenStorage,
    OAuthToken,
)
from app.notifications.google_chat.provider import GoogleChatNotificationProvider
from app.notifications.service import NotificationService
from app.services.decision_engine import DecisionResult


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(name="db_session")
def fixture_db_session():
    """In-memory database session for notification testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="configured_subject")
def fixture_configured_subject(db_session: Session) -> Subject:
    """Create test subject with professor mapping."""
    subject = Subject(code="CS101", name="Python Programming")
    db_session.add(subject)
    db_session.flush()
    mapping = ProfessorMapping(
        subject_id=subject.id,
        professor_name="Dr. Alan Turing",
        professor_email="turing@university.edu",
    )
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(subject)
    return subject


@pytest.fixture(name="sample_chat_payload")
def fixture_sample_chat_payload() -> NotificationPayload:
    return NotificationPayload(
        subject_code="CS101",
        subject_name="Python Programming",
        target_date=date(2026, 9, 27),
        recipient_email="turing@university.edu",
        professor_name="Dr. Alan Turing",
        message_subject="Attendance Review Request – CS101 – 27 September 2026",
        message_body="Dear Dr. Alan Turing,\n\nCould you kindly review the attendance record?\n\nWarm regards,\nAlice",
        student_name="Alice",
    )


@pytest.fixture(name="mock_oauth_client")
def fixture_mock_oauth_client():
    client = MagicMock(spec=GoogleChatOAuthClient)
    client.get_valid_access_token.return_value = "mock_valid_access_token"
    return client


# ═══════════════════════════════════════════════════════════════════════════
# 1. GoogleChatConfig validation and secret redaction
# ═══════════════════════════════════════════════════════════════════════════


class TestGoogleChatConfig:
    def test_default_config(self):
        config = GoogleChatConfig()
        assert config.client_id is None
        assert config.client_secret is None
        assert config.is_oauth_configured() is False
        assert "https://www.googleapis.com/auth/chat.messages.create" in config.scopes

    def test_is_oauth_configured(self):
        cfg_empty = GoogleChatConfig()
        assert cfg_empty.is_oauth_configured() is False

        cfg_partial = GoogleChatConfig(client_id="dummy_id")
        assert cfg_partial.is_oauth_configured() is False

        cfg_ready = GoogleChatConfig(client_id="dummy_id", client_secret="dummy_secret")
        assert cfg_ready.is_oauth_configured() is True

    def test_validate_oauth_raises_when_unconfigured(self):
        with pytest.raises(OAuthConfigurationError, match="client_id is not configured"):
            GoogleChatConfig(client_id=None, client_secret="secret").validate_oauth()

        with pytest.raises(OAuthConfigurationError, match="client_secret is not configured"):
            GoogleChatConfig(client_id="client_id", client_secret=None).validate_oauth()

    def test_validate_space_configuration_raises_when_no_space(self):
        cfg = GoogleChatConfig(default_space=None, recipient_space_mapping={})
        with pytest.raises(OAuthConfigurationError, match="Neither default_space nor recipient_space_mapping"):
            cfg.validate_space_configuration()

    def test_validate_space_configuration_passes_with_default_or_mapping(self):
        cfg1 = GoogleChatConfig(default_space="spaces/DEFAULT")
        assert cfg1.validate_space_configuration() is True

        cfg2 = GoogleChatConfig(recipient_space_mapping={"turing@university.edu": "spaces/TURING"})
        assert cfg2.validate_space_configuration() is True

    def test_safe_dict_redacts_client_secret(self):
        cfg = GoogleChatConfig(client_id="cid123", client_secret="super_secret_key_456")
        safe = cfg.safe_dict()
        assert safe["client_id"] == "cid123"
        assert safe["client_secret"] == "[REDACTED]"
        assert "super_secret_key_456" not in str(safe)

    def test_repr_masks_client_secret(self):
        cfg = GoogleChatConfig(client_id="cid123", client_secret="super_secret_key_456")
        repr_str = repr(cfg)
        assert "super_secret_key_456" not in repr_str
        assert "[REDACTED]" in repr_str


# ═══════════════════════════════════════════════════════════════════════════
# 2. OAuthToken lifecycle, expiration, and credential masking
# ═══════════════════════════════════════════════════════════════════════════


class TestOAuthToken:
    def test_is_expired(self):
        now = time.time()
        # Token expiring in 10 minutes -> not expired
        valid_token = OAuthToken(access_token="tok", expires_at=now + 600)
        assert valid_token.is_expired() is False

        # Token expiring in 30 seconds -> expired with default 60s buffer
        expiring_token = OAuthToken(access_token="tok", expires_at=now + 30)
        assert expiring_token.is_expired(buffer_seconds=60) is True

        # Token expired 10 minutes ago
        expired_token = OAuthToken(access_token="tok", expires_at=now - 600)
        assert expired_token.is_expired() is True

        # Token with no expiration
        timeless_token = OAuthToken(access_token="tok", expires_at=None)
        assert timeless_token.is_expired() is False

    def test_token_repr_masks_secrets(self):
        token = OAuthToken(
            access_token="secret_access_token_12345",
            refresh_token="secret_refresh_token_67890",
        )
        assert "secret_access_token_12345" not in repr(token)
        assert "secret_refresh_token_67890" not in repr(token)
        assert "secret_access_token_12345" not in str(token)
        assert "[REDACTED]" in repr(token)

    def test_serialization_roundtrip(self):
        token = OAuthToken(
            access_token="acc",
            refresh_token="ref",
            token_type="Bearer",
            expires_at=1234567.0,
            scope="chat.messages.create",
        )
        d = token.to_dict()
        reconstructed = OAuthToken.from_dict(d)
        assert reconstructed.access_token == "acc"
        assert reconstructed.refresh_token == "ref"
        assert reconstructed.expires_at == 1234567.0
        assert reconstructed.scope == "chat.messages.create"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Token storage implementations
# ═══════════════════════════════════════════════════════════════════════════


class TestTokenStorage:
    def test_in_memory_storage(self):
        storage = InMemoryTokenStorage()
        assert storage.load_token() is None

        token = OAuthToken(access_token="acc123", refresh_token="ref456")
        storage.save_token(token)
        loaded = storage.load_token()
        assert loaded is not None
        assert loaded.access_token == "acc123"

        storage.clear_token()
        assert storage.load_token() is None

    def test_file_storage(self, tmp_path):
        token_path = str(tmp_path / "credentials" / "chat_token.json")
        storage = FileTokenStorage(token_path)
        assert storage.load_token() is None

        token = OAuthToken(
            access_token="acc_test",
            refresh_token="ref_test",
            expires_at=1800000000.0,
        )
        storage.save_token(token)

        # Verify file exists
        assert os.path.exists(token_path)

        # Check POSIX permissions (0600)
        mode = os.stat(token_path).st_mode
        assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0  # No group or other access

        # Load back
        loaded = storage.load_token()
        assert loaded is not None
        assert loaded.access_token == "acc_test"
        assert loaded.refresh_token == "ref_test"

        # Clear
        storage.clear_token()
        assert not os.path.exists(token_path)
        assert storage.load_token() is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. GoogleChatOAuthClient
# ═══════════════════════════════════════════════════════════════════════════


class TestGoogleChatOAuthClient:
    def test_authorization_url_generation(self):
        config = GoogleChatConfig(
            client_id="test_client_id.apps.googleusercontent.com",
            client_secret="test_client_secret",
            redirect_uri="http://localhost:8000/callback",
        )
        oauth = GoogleChatOAuthClient(config=config)
        url, state = oauth.get_authorization_url(state="custom_csrf_state")

        assert "https://accounts.google.com/o/oauth2/v2/auth" in url
        assert "client_id=test_client_id.apps.googleusercontent.com" in url
        assert "state=custom_csrf_state" in url
        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert state == "custom_csrf_state"

    def test_authorization_url_unconfigured_raises(self):
        oauth = GoogleChatOAuthClient(config=GoogleChatConfig())
        with pytest.raises(OAuthConfigurationError):
            oauth.get_authorization_url()

    def test_exchange_code_for_token_success(self):
        config = GoogleChatConfig(
            client_id="cid",
            client_secret="csec",
            redirect_uri="http://localhost:8000/callback",
        )
        storage = InMemoryTokenStorage()

        mock_http = MagicMock(spec=httpx.Client)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token_abc",
            "refresh_token": "new_refresh_token_xyz",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/chat.messages.create",
        }
        mock_http.post.return_value = mock_response

        oauth = GoogleChatOAuthClient(config=config, token_storage=storage, http_client=mock_http)
        token = oauth.exchange_code_for_token(code="auth_code_123", state="st", expected_state="st")

        assert token.access_token == "new_access_token_abc"
        assert token.refresh_token == "new_refresh_token_xyz"
        assert storage.load_token() == token

        # Verify POST payload
        mock_http.post.assert_called_once()
        post_kwargs = mock_http.post.call_args[1]
        assert post_kwargs["data"]["code"] == "auth_code_123"
        assert post_kwargs["data"]["grant_type"] == "authorization_code"

    def test_exchange_code_state_mismatch_raises(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        oauth = GoogleChatOAuthClient(config=config)
        with pytest.raises(OAuthAuthenticationError, match="state parameter mismatch"):
            oauth.exchange_code_for_token(code="code", state="state_A", expected_state="state_B")

    def test_exchange_code_missing_code_raises(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        oauth = GoogleChatOAuthClient(config=config)
        with pytest.raises(OAuthAuthenticationError, match="code is empty"):
            oauth.exchange_code_for_token(code="")

    def test_exchange_code_api_error_raises_cleanly(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_grant", "error_description": "Bad code"}
        mock_http.post.return_value = mock_resp

        oauth = GoogleChatOAuthClient(config=config, http_client=mock_http)
        with pytest.raises(OAuthAuthenticationError, match="Bad code"):
            oauth.exchange_code_for_token(code="invalid_code")

    def test_refresh_token_success(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        storage = InMemoryTokenStorage(
            initial_token=OAuthToken(access_token="old_acc", refresh_token="valid_ref")
        )

        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "refreshed_acc",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_http.post.return_value = mock_resp

        oauth = GoogleChatOAuthClient(config=config, token_storage=storage, http_client=mock_http)
        updated = oauth.refresh_access_token()

        assert updated.access_token == "refreshed_acc"
        # Preserves previous refresh token if not returned
        assert updated.refresh_token == "valid_ref"
        assert storage.load_token().access_token == "refreshed_acc"

    def test_refresh_token_missing_raises(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        storage = InMemoryTokenStorage(initial_token=OAuthToken(access_token="acc", refresh_token=None))
        oauth = GoogleChatOAuthClient(config=config, token_storage=storage)

        with pytest.raises(OAuthAuthenticationError, match="No refresh token available"):
            oauth.refresh_access_token()

    def test_get_valid_access_token_not_expired(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        storage = InMemoryTokenStorage(
            initial_token=OAuthToken(access_token="active_token", expires_at=time.time() + 3600)
        )
        oauth = GoogleChatOAuthClient(config=config, token_storage=storage)
        assert oauth.get_valid_access_token() == "active_token"

    def test_get_valid_access_token_expired_triggers_refresh(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        storage = InMemoryTokenStorage(
            initial_token=OAuthToken(
                access_token="expired_token",
                refresh_token="my_ref",
                expires_at=time.time() - 100,
            )
        )
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "newly_refreshed_token", "expires_in": 3600}
        mock_http.post.return_value = mock_resp

        oauth = GoogleChatOAuthClient(config=config, token_storage=storage, http_client=mock_http)
        token = oauth.get_valid_access_token()

        assert token == "newly_refreshed_token"

    def test_get_valid_access_token_unconfigured_raises(self):
        oauth = GoogleChatOAuthClient(config=GoogleChatConfig())
        with pytest.raises(OAuthConfigurationError):
            oauth.get_valid_access_token()

    def test_get_valid_access_token_missing_token_raises(self):
        config = GoogleChatConfig(client_id="cid", client_secret="csec")
        oauth = GoogleChatOAuthClient(config=config, token_storage=InMemoryTokenStorage())
        with pytest.raises(OAuthAuthenticationError, match="No token found"):
            oauth.get_valid_access_token()


# ═══════════════════════════════════════════════════════════════════════════
# 5. GoogleChatClient
# ═══════════════════════════════════════════════════════════════════════════


class TestGoogleChatClient:
    def test_normalize_space_name(self):
        assert GoogleChatClient.normalize_space_name("spaces/AAAA123") == "spaces/AAAA123"
        assert GoogleChatClient.normalize_space_name("AAAA123") == "spaces/AAAA123"
        assert GoogleChatClient.normalize_space_name("  spaces/XYZ  ") == "spaces/XYZ"

        with pytest.raises(GoogleChatRecipientError, match="cannot be empty"):
            GoogleChatClient.normalize_space_name("   ")

    def test_send_message_success(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "name": "spaces/AAAA123/messages/msg_987",
            "text": "Hello world",
        }
        mock_http.post.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        result = client.send_message(space_name="AAAA123", text="Hello world")

        assert result["name"] == "spaces/AAAA123/messages/msg_987"
        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        assert call_args[0][0] == "https://chat.googleapis.com/v1/spaces/AAAA123/messages"
        assert call_args[1]["headers"]["Authorization"] == "Bearer mock_valid_access_token"
        assert call_args[1]["json"]["text"] == "Hello world"

    def test_send_message_401_raises_auth_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": {"message": "Invalid credentials"}}
        mock_http.post.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(OAuthAuthenticationError, match="401 Unauthorized"):
            client.send_message(space_name="spaces/X", text="test")

    def test_send_message_403_raises_permission_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"error": {"message": "Caller lacks permissions"}}
        mock_http.post.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatPermissionError, match="403 Forbidden"):
            client.send_message(space_name="spaces/X", text="test")

    def test_send_message_404_raises_recipient_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"error": {"message": "Space not found"}}
        mock_http.post.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatRecipientError, match="404 Not Found"):
            client.send_message(space_name="spaces/MISSING", text="test")

    def test_send_message_429_raises_rate_limit(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": {"message": "Quota exceeded"}}
        mock_http.post.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatRateLimitError, match="429 RESOURCE_EXHAUSTED"):
            client.send_message(space_name="spaces/X", text="test")

    def test_send_message_500_raises_api_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": {"message": "Internal error"}}
        mock_http.post.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatApiError, match="server error"):
            client.send_message(space_name="spaces/X", text="test")

    def test_send_message_timeout_raises_api_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.post.side_effect = httpx.TimeoutException("Connection timed out")

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatApiError, match="Network timeout"):
            client.send_message(space_name="spaces/X", text="test")

    def test_find_direct_message_success(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "name": "spaces/DM_SPACE_123",
            "type": "DIRECT_MESSAGE",
            "spaceType": "DIRECT_MESSAGE",
        }
        mock_http.get.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        result = client.find_direct_message("professor@university.edu")

        assert result["name"] == "spaces/DM_SPACE_123"
        mock_http.get.assert_called_once()
        call_args = mock_http.get.call_args
        assert call_args[0][0] == "https://chat.googleapis.com/v1/spaces:findDirectMessage"
        assert call_args[1]["params"]["name"] == "users/professor@university.edu"
        assert call_args[1]["headers"]["Authorization"] == "Bearer mock_valid_access_token"

    def test_find_direct_message_invalid_email(self, mock_oauth_client):
        client = GoogleChatClient(oauth_client=mock_oauth_client)
        with pytest.raises(GoogleChatRecipientError, match="Invalid professor email"):
            client.find_direct_message("not-an-email")
        with pytest.raises(GoogleChatRecipientError, match="Invalid professor email"):
            client.find_direct_message("   ")

    def test_find_direct_message_400_recipient_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": {"message": "Invalid user resource"}}
        mock_http.get.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatRecipientError, match="Cannot find Google Chat user"):
            client.find_direct_message("unknown@university.edu")

    def test_find_direct_message_401_auth_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": {"message": "Invalid credentials"}}
        mock_http.get.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(OAuthAuthenticationError, match="401 Unauthorized"):
            client.find_direct_message("prof@uni.edu")

    def test_find_direct_message_403_insufficient_scope(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"error": {"message": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}}
        mock_http.get.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatPermissionError, match="chat.spaces.readonly"):
            client.find_direct_message("prof@uni.edu")

    def test_find_direct_message_404_no_dm_exists(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"error": {"message": "Space not found"}}
        mock_http.get.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatRecipientError, match="No direct message space exists"):
            client.find_direct_message("prof@uni.edu")

    def test_find_direct_message_429_rate_limit(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": {"message": "Rate limit exceeded"}}
        mock_http.get.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatRateLimitError, match="429 RESOURCE_EXHAUSTED"):
            client.find_direct_message("prof@uni.edu")

    def test_find_direct_message_500_api_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 503
        mock_resp.json.return_value = {"error": {"message": "Service unavailable"}}
        mock_http.get.return_value = mock_resp

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatApiError, match="server error"):
            client.find_direct_message("prof@uni.edu")

    def test_find_direct_message_timeout(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get.side_effect = httpx.TimeoutException("Read timed out")

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatApiError, match="Network timeout"):
            client.find_direct_message("prof@uni.edu")

    def test_find_direct_message_request_error(self, mock_oauth_client):
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get.side_effect = httpx.ConnectError("Connection refused")

        client = GoogleChatClient(oauth_client=mock_oauth_client, http_client=mock_http)
        with pytest.raises(GoogleChatApiError, match="Network error"):
            client.find_direct_message("prof@uni.edu")



# ═══════════════════════════════════════════════════════════════════════════
# 6. GoogleChatNotificationProvider
# ═══════════════════════════════════════════════════════════════════════════


class TestGoogleChatNotificationProvider:
    def test_provider_properties(self):
        provider = GoogleChatNotificationProvider()
        assert provider.provider_name == "google_chat"
        assert provider.is_dry_run is False
        assert isinstance(provider, BaseNotificationProvider)

    def test_validate_config_success(self):
        cfg = GoogleChatConfig(
            client_id="cid",
            client_secret="csec",
            default_space="spaces/DEFAULT",
        )
        provider = GoogleChatNotificationProvider(config=cfg)
        assert provider.validate_config() is True

    def test_validate_config_missing_oauth_raises(self):
        cfg = GoogleChatConfig(default_space="spaces/DEFAULT")
        provider = GoogleChatNotificationProvider(config=cfg)
        with pytest.raises(OAuthConfigurationError):
            provider.validate_config()

    def test_validate_config_missing_space_raises(self):
        cfg = GoogleChatConfig(client_id="cid", client_secret="csec")
        provider = GoogleChatNotificationProvider(config=cfg)
        with pytest.raises(OAuthConfigurationError):
            provider.validate_config()

    def test_space_resolution_precedence(self):
        cfg = GoogleChatConfig(
            default_space="spaces/FALLBACK",
            recipient_space_mapping={"prof@uni.edu": "spaces/MAPPED"},
        )
        provider = GoogleChatNotificationProvider(config=cfg)

        # 1. Metadata takes highest precedence
        p1 = NotificationPayload(
            subject_code="CS101",
            subject_name="Python",
            target_date=date(2026, 9, 27),
            recipient_email="prof@uni.edu",
            professor_name="Prof",
            message_subject="Sub",
            message_body="Body",
            metadata={"space_id": "spaces/OVERRIDE"},
        )
        assert provider.resolve_space(p1) == "spaces/OVERRIDE"

        # 2. Recipient mapping takes second precedence
        p2 = NotificationPayload(
            subject_code="CS101",
            subject_name="Python",
            target_date=date(2026, 9, 27),
            recipient_email="prof@uni.edu",
            professor_name="Prof",
            message_subject="Sub",
            message_body="Body",
        )
        assert provider.resolve_space(p2) == "spaces/MAPPED"

        # 3. Default space fallback
        p3 = NotificationPayload(
            subject_code="CS101",
            subject_name="Python",
            target_date=date(2026, 9, 27),
            recipient_email="unknown@uni.edu",
            professor_name="Prof",
            message_subject="Sub",
            message_body="Body",
        )
        assert provider.resolve_space(p3) == "spaces/FALLBACK"

    def test_space_resolution_missing_fails(self):
        provider = GoogleChatNotificationProvider(config=GoogleChatConfig())
        payload = NotificationPayload(
            subject_code="CS101",
            subject_name="Python",
            target_date=date(2026, 9, 27),
            recipient_email="prof@uni.edu",
            professor_name="Prof",
            message_subject="Sub",
            message_body="Body",
        )
        with pytest.raises(GoogleChatRecipientError, match="No Google Chat space configured"):
            provider.resolve_space(payload)

    def test_send_successful(self, sample_chat_payload):
        cfg = GoogleChatConfig(default_space="spaces/DEFAULT")
        mock_api = MagicMock(spec=GoogleChatClient)
        mock_api.send_message.return_value = {"name": "spaces/DEFAULT/messages/msg_123"}

        provider = GoogleChatNotificationProvider(config=cfg, api_client=mock_api)
        outcome = provider.send(sample_chat_payload)

        assert outcome.success is True
        assert outcome.provider_name == "google_chat"
        assert outcome.is_dry_run is False
        assert outcome.error_message is None
        assert outcome.details["space"] == "spaces/DEFAULT"
        assert outcome.details["message_id"] == "spaces/DEFAULT/messages/msg_123"
        assert sample_chat_payload.recipient_email in outcome.message_preview

    def test_send_invalid_recipient_fails_safely(self, sample_chat_payload):
        cfg = GoogleChatConfig(default_space="spaces/DEFAULT")
        provider = GoogleChatNotificationProvider(config=cfg)

        invalid_payload = NotificationPayload(
            subject_code="CS101",
            subject_name="Python",
            target_date=date(2026, 9, 27),
            recipient_email="not-an-email",
            professor_name="Prof",
            message_subject="Sub",
            message_body="Body",
        )
        outcome = provider.send(invalid_payload)

        assert outcome.success is False
        assert outcome.is_dry_run is False
        assert "Invalid recipient email" in outcome.error_message

    def test_send_unresolvable_space_fails_safely(self, sample_chat_payload):
        provider = GoogleChatNotificationProvider(config=GoogleChatConfig())
        outcome = provider.send(sample_chat_payload)

        assert outcome.success is False
        assert "No Google Chat space configured" in outcome.error_message

    def test_send_handles_permission_error_safely(self, sample_chat_payload):
        cfg = GoogleChatConfig(default_space="spaces/DEFAULT")
        mock_api = MagicMock(spec=GoogleChatClient)
        mock_api.send_message.side_effect = GoogleChatPermissionError("Forbidden (403)")

        provider = GoogleChatNotificationProvider(config=cfg, api_client=mock_api)
        outcome = provider.send(sample_chat_payload)

        assert outcome.success is False
        assert "Forbidden (403)" in outcome.error_message
        assert outcome.details["error_type"] == "GoogleChatPermissionError"

    def test_send_handles_rate_limit_safely(self, sample_chat_payload):
        cfg = GoogleChatConfig(default_space="spaces/DEFAULT")
        mock_api = MagicMock(spec=GoogleChatClient)
        mock_api.send_message.side_effect = GoogleChatRateLimitError("429 Quota exceeded")

        provider = GoogleChatNotificationProvider(config=cfg, api_client=mock_api)
        outcome = provider.send(sample_chat_payload)

        assert outcome.success is False
        assert "429 Quota exceeded" in outcome.error_message


# ═══════════════════════════════════════════════════════════════════════════
# 7. NotificationService integration & safety invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestGoogleChatServiceIntegration:
    """Verify Google Chat provider interaction with NotificationService and Decision Engine."""

    def test_service_dispatches_eligible_decision_to_google_chat(
        self, db_session: Session, configured_subject: Subject
    ):
        cfg = GoogleChatConfig(default_space="spaces/CS101_ROOM")
        mock_api = MagicMock(spec=GoogleChatClient)
        mock_api.send_message.return_value = {"name": "spaces/CS101_ROOM/messages/msg_abc"}

        provider = GoogleChatNotificationProvider(config=cfg, api_client=mock_api)
        service = NotificationService(provider=provider, db=db_session, student_name="Alice")

        decision = DecisionResult(
            action=DecisionAction.ELIGIBLE_FOR_NOTIFICATION,
            reason=DecisionReason.ABSENT_AND_CONFIRMED,
            subject_code="CS101",
            target_date=date(2026, 9, 27),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
            professor_email="turing@university.edu",
        )

        outcome = service.process_decision(decision)

        # Provider send called
        assert outcome is not None
        assert outcome.success is True
        assert outcome.provider_name == "google_chat"
        assert outcome.is_dry_run is False

        # NotificationEvent persisted in DB as SENT
        events = db_session.query(NotificationEvent).filter(
            NotificationEvent.subject_code == "CS101"
        ).all()
        assert len(events) == 1
        assert events[0].status == NotificationStatus.SENT
        assert events[0].dry_run is False
        assert events[0].sent_at is not None

        # AuditEvent persisted as NOTIFICATION_SENT
        audit_records = db_session.query(AuditEvent).filter(
            AuditEvent.event_type == AuditEventType.NOTIFICATION
        ).all()
        assert len(audit_records) == 1
        assert audit_records[0].action == "NOTIFICATION_SENT"

    def test_service_records_failed_event_when_google_chat_fails(
        self, db_session: Session, configured_subject: Subject
    ):
        cfg = GoogleChatConfig(default_space="spaces/CS101_ROOM")
        mock_api = MagicMock(spec=GoogleChatClient)
        mock_api.send_message.side_effect = GoogleChatApiError("Google Chat Service Unavailable (503)")

        provider = GoogleChatNotificationProvider(config=cfg, api_client=mock_api)
        service = NotificationService(provider=provider, db=db_session)

        decision = DecisionResult(
            action=DecisionAction.ELIGIBLE_FOR_NOTIFICATION,
            reason=DecisionReason.ABSENT_AND_CONFIRMED,
            subject_code="CS101",
            target_date=date(2026, 9, 27),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
            professor_email="turing@university.edu",
        )

        outcome = service.process_decision(decision)

        assert outcome is not None
        assert outcome.success is False
        assert "Service Unavailable" in outcome.error_message

        # Database event recorded as FAILED
        events = db_session.query(NotificationEvent).all()
        assert len(events) == 1
        assert events[0].status == NotificationStatus.FAILED
        assert "Service Unavailable" in events[0].error_message

        # Audit recorded as NOTIFICATION_FAILED
        audit = db_session.query(AuditEvent).filter(AuditEvent.event_type == AuditEventType.NOTIFICATION).first()
        assert audit is not None
        assert audit.action == "NOTIFICATION_FAILED"

    def test_service_never_dispatches_ineligible_to_google_chat(
        self, db_session: Session, configured_subject: Subject
    ):
        """CRITICAL SAFETY: NotificationService must drop all ineligible decisions before touching provider."""
        mock_api = MagicMock(spec=GoogleChatClient)
        provider = GoogleChatNotificationProvider(api_client=mock_api)
        service = NotificationService(provider=provider, db=db_session)

        ineligible_reasons = [
            (DecisionReason.STATUS_PRESENT, AttendanceStatus.PRESENT, True, True),
            (DecisionReason.STATUS_UNKNOWN, AttendanceStatus.UNKNOWN, True, True),
            (DecisionReason.UNRELIABLE_ATTENDANCE_RESULT, AttendanceStatus.ABSENT, False, True),
            (DecisionReason.ATTENDANCE_NOT_CONFIRMED, AttendanceStatus.ABSENT, True, False),
            (DecisionReason.ALREADY_NOTIFIED, AttendanceStatus.ABSENT, True, True),
        ]

        for reason, status, is_rel, is_conf in ineligible_reasons:
            decision = DecisionResult(
                action=DecisionAction.NO_ACTION,
                reason=reason,
                subject_code="CS101",
                target_date=date(2026, 9, 27),
                is_confirmed=is_conf,
                status=status,
                is_reliable=is_rel,
                professor_email="turing@university.edu",
            )
            outcome = service.process_decision(decision)
            assert outcome is None

        # Verify Google Chat API was NEVER called
        mock_api.send_message.assert_not_called()

    def test_provider_does_not_mutate_decision_or_records(
        self, db_session: Session, configured_subject: Subject
    ):
        """CRITICAL SAFETY: A Google Chat delivery failure must NEVER alter attendance or decision data."""
        from app.models.attendance_check import AttendanceCheck
        from app.models.attendance_result import AttendanceResult
        from app.core.enums import CheckStatus

        # Simulate pre-existing attendance check and result
        check = AttendanceCheck(
            run_id="run-1",
            check_date=date(2026, 9, 27),
            adapter_name="fake",
            status=CheckStatus.SUCCESS,
        )
        db_session.add(check)
        db_session.flush()

        res = AttendanceResult(
            check_id=check.id,
            subject_id=configured_subject.id,
            subject_code="CS101",
            status=AttendanceStatus.ABSENT,
            raw_status="A",
            is_reliable=True,
        )
        db_session.add(res)
        db_session.commit()

        # Failing Google Chat provider
        mock_api = MagicMock(spec=GoogleChatClient)
        mock_api.send_message.side_effect = GoogleChatError("Fatal Chat Network Disconnect")

        provider = GoogleChatNotificationProvider(
            config=GoogleChatConfig(default_space="spaces/X"),
            api_client=mock_api,
        )
        service = NotificationService(provider=provider, db=db_session)

        decision = DecisionResult(
            action=DecisionAction.ELIGIBLE_FOR_NOTIFICATION,
            reason=DecisionReason.ABSENT_AND_CONFIRMED,
            subject_code="CS101",
            target_date=date(2026, 9, 27),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
            professor_email="turing@university.edu",
        )

        outcome = service.process_decision(decision)
        assert outcome.success is False

        # Verify AttendanceResult and AttendanceCheck are untouched
        db_session.refresh(res)
        db_session.refresh(check)
        assert res.status == AttendanceStatus.ABSENT
        assert res.is_reliable is True
        assert check.status == CheckStatus.SUCCESS

    def test_dry_run_provider_remains_fully_functional(self, db_session: Session, configured_subject: Subject):
        """Verifies backward compatibility with DryRunNotificationProvider."""
        dry_run = DryRunNotificationProvider()
        service = NotificationService(provider=dry_run, db=db_session)

        decision = DecisionResult(
            action=DecisionAction.ELIGIBLE_FOR_NOTIFICATION,
            reason=DecisionReason.ABSENT_AND_CONFIRMED,
            subject_code="CS101",
            target_date=date(2026, 9, 27),
            is_confirmed=True,
            status=AttendanceStatus.ABSENT,
            is_reliable=True,
            professor_email="turing@university.edu",
        )

        outcome = service.process_decision(decision)
        assert outcome.success is True
        assert outcome.is_dry_run is True
        assert outcome.provider_name == "dry_run"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Structural network safety
# ═══════════════════════════════════════════════════════════════════════════


class TestNetworkIsolation:
    def test_no_real_socket_connection_during_unit_tests(self, sample_chat_payload):
        """Ensure unit tests do not attempt real outbound network sockets."""
        original_socket = socket.socket

        def guarded_socket(*args, **kwargs):
            raise AssertionError("Unit test attempted to establish an outbound network socket!")

        socket.socket = guarded_socket  # type: ignore[assignment]
        try:
            cfg = GoogleChatConfig(default_space="spaces/DEFAULT")
            mock_api = MagicMock(spec=GoogleChatClient)
            mock_api.send_message.return_value = {"name": "spaces/DEFAULT/messages/msg_1"}

            provider = GoogleChatNotificationProvider(config=cfg, api_client=mock_api)
            outcome = provider.send(sample_chat_payload)
            assert outcome.success is True
        finally:
            socket.socket = original_socket  # type: ignore[assignment]
