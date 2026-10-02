"""Unit tests for GoogleChatOAuthService, OAuthStateManager, and recipient space routing."""

import socket
import time
from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.core.enums import AttendanceStatus, DecisionAction, DecisionReason, NotificationStatus
from app.database.base import Base
from app.models.notification_event import NotificationEvent
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.base import NotificationPayload
from app.notifications.google_chat.client import GoogleChatClient
from app.notifications.google_chat.config import GoogleChatConfig
from app.notifications.google_chat.exceptions import (
    GoogleChatRecipientError,
    OAuthAuthenticationError,
    OAuthConfigurationError,
)
from app.notifications.google_chat.oauth import InMemoryTokenStorage, OAuthToken
from app.notifications.google_chat.provider import GoogleChatNotificationProvider
from app.notifications.service import NotificationService
from app.services.decision_engine import DecisionResult
from app.services.google_chat_oauth_service import (
    GoogleChatOAuthService,
    OAuthStateManager,
)


@pytest.fixture(name="db_session")
def fixture_db_session():
    """In-memory database session."""
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
    """Subject with professor mapping but NO Google Chat space initially."""
    subject = Subject(code="CS101", name="Python Programming")
    db_session.add(subject)
    db_session.flush()

    mapping = ProfessorMapping(
        subject_id=subject.id,
        professor_name="Dr. Alan Turing",
        professor_email="turing@university.edu",
        google_chat_space=None,  # Intentionally unconfigured
    )
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(subject)
    return subject


# ═══════════════════════════════════════════════════════════════════════════
# 1. OAuthStateManager Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestOAuthStateManager:
    def test_state_generation_and_consumption(self):
        manager = OAuthStateManager(ttl_seconds=300)
        state = manager.generate_state()
        assert len(state) >= 32

        # First consumption succeeds
        assert manager.validate_and_consume(state) is True

        # Second consumption fails (prevent replay)
        assert manager.validate_and_consume(state) is False

    def test_state_expiration(self):
        manager = OAuthStateManager(ttl_seconds=-1)  # Expired immediately
        state = manager.generate_state()

        assert manager.validate_and_consume(state) is False

    def test_invalid_or_empty_state(self):
        manager = OAuthStateManager(ttl_seconds=300)
        assert manager.validate_and_consume(None) is False
        assert manager.validate_and_consume("") is False
        assert manager.validate_and_consume("random_string") is False

    def test_cleanup_expired(self):
        manager = OAuthStateManager(ttl_seconds=300)
        manager._states["expired_token"] = time.time() - 100
        manager._states["valid_token"] = time.time() + 100

        manager.cleanup_expired()
        assert "expired_token" not in manager._states
        assert "valid_token" in manager._states


# ═══════════════════════════════════════════════════════════════════════════
# 2. GoogleChatOAuthService Unit Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGoogleChatOAuthService:
    def test_is_configured_logic(self):
        s_unconf = Settings(google_chat_client_id=None, google_chat_client_secret=None)
        svc_unconf = GoogleChatOAuthService(settings=s_unconf)
        assert svc_unconf.is_configured() is False

        s_partial = Settings(google_chat_client_id="id", google_chat_client_secret=None)
        svc_partial = GoogleChatOAuthService(settings=s_partial)
        assert svc_partial.is_configured() is False

        s_full = Settings(google_chat_client_id="id", google_chat_client_secret="sec")
        svc_full = GoogleChatOAuthService(settings=s_full)
        assert svc_full.is_configured() is True

    def test_get_authorization_url_unconfigured_raises(self):
        s = Settings(google_chat_client_id=None, google_chat_client_secret=None)
        svc = GoogleChatOAuthService(settings=s)
        with pytest.raises(OAuthConfigurationError, match="Google Chat OAuth is not configured"):
            svc.get_authorization_url()

    def test_handle_callback_error_raises_auth_error(self):
        s = Settings(google_chat_client_id="id", google_chat_client_secret="sec")
        svc = GoogleChatOAuthService(settings=s)
        with pytest.raises(OAuthAuthenticationError, match="denied or cancelled by user"):
            svc.handle_callback(code=None, state="any", error="access_denied", error_description="Cancelled")

    def test_handle_callback_invalid_state_raises(self):
        s = Settings(google_chat_client_id="id", google_chat_client_secret="sec")
        svc = GoogleChatOAuthService(settings=s)
        with pytest.raises(OAuthAuthenticationError, match="Invalid or expired OAuth state parameter"):
            svc.handle_callback(code="code_123", state="invalid_state")

    def test_handle_callback_missing_code_raises(self):
        s = Settings(google_chat_client_id="id", google_chat_client_secret="sec")
        state_mgr = OAuthStateManager()
        state = state_mgr.generate_state()
        svc = GoogleChatOAuthService(settings=s, state_manager=state_mgr)

        with pytest.raises(OAuthAuthenticationError, match="Authorization code is missing"):
            svc.handle_callback(code=None, state=state)

    def test_status_expired_token_reporting(self):
        s = Settings(google_chat_client_id="id", google_chat_client_secret="sec")
        storage = InMemoryTokenStorage(
            initial_token=OAuthToken(
                access_token="expired_tok",
                refresh_token="valid_ref",
                expires_at=time.time() - 3600,
            )
        )
        svc = GoogleChatOAuthService(settings=s, token_storage=storage)
        st = svc.get_connection_status()

        assert st["configured"] is True
        assert st["connected"] is True  # Connected because refresh token exists
        assert st["is_expired"] is True
        assert st["has_refresh_token"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 3. Recipient/Space Mapping & Unconfigured Recipient Safety Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRecipientSpaceSafety:
    def test_unconfigured_recipient_fails_closed_without_crash(
        self,
        db_session: Session,
        configured_subject: Subject,
    ):
        """CRITICAL REQUIREMENT: Unconfigured professors remain safely unconfigured.

        If a subject has a professor with NO google_chat_space and NO default space is configured:
        - The NotificationService processes the eligible decision.
        - The provider fails safely (GoogleChatRecipientError handled).
        - A FAILED NotificationEvent is recorded in the database.
        - NO unhandled exceptions are raised.
        - Attendance records and decision results remain unaltered.
        """
        # Google Chat config with NO default space and NO mappings
        cfg = GoogleChatConfig(
            client_id="cid",
            client_secret="csec",
            default_space=None,
            recipient_space_mapping={},
        )
        mock_api = MagicMock(spec=GoogleChatClient)
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

        # Provider send failed closed safely
        assert outcome is not None
        assert outcome.success is False
        assert "No Google Chat space configured" in outcome.error_message

        # Google Chat API send_message was NEVER called
        mock_api.send_message.assert_not_called()

        # Database recorded event as FAILED
        event = db_session.query(NotificationEvent).filter(NotificationEvent.subject_code == "CS101").first()
        assert event is not None
        assert event.status == NotificationStatus.FAILED
        assert "No Google Chat space configured" in event.error_message

    def test_configured_professor_space_routes_successfully(
        self,
        db_session: Session,
        configured_subject: Subject,
    ):
        """When a professor has a google_chat_space configured, message routes to that space."""
        # Update subject's professor mapping with a space
        configured_subject.professor_mapping.google_chat_space = "spaces/TURING_OFFICE"
        db_session.commit()

        cfg = GoogleChatConfig(
            client_id="cid",
            client_secret="csec",
            default_space="spaces/SHOULD_NOT_BE_USED",
        )
        mock_api = MagicMock(spec=GoogleChatClient)
        mock_api.send_message.return_value = {"name": "spaces/TURING_OFFICE/messages/msg_999"}

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

        assert outcome is not None
        assert outcome.success is True
        assert outcome.details["space"] == "spaces/TURING_OFFICE"

        # Verify Google Chat API was invoked with the professor's space
        mock_api.send_message.assert_called_once()
        assert mock_api.send_message.call_args[1]["space_name"] == "spaces/TURING_OFFICE"

        # Event saved as SENT
        event = db_session.query(NotificationEvent).filter(NotificationEvent.subject_code == "CS101").first()
        assert event.status == NotificationStatus.SENT

    def test_professor_space_update_and_clear_service(
        self,
        db_session: Session,
        configured_subject: Subject,
    ):
        """Verify update_professor_space and clear space via service."""
        svc = GoogleChatOAuthService(settings=Settings())

        # 1. Update space
        res = svc.update_professor_space(db_session, "CS101", "spaces/ROOM_404")
        assert res["google_chat_space"] == "spaces/ROOM_404"
        assert res["is_configured"] is True

        # 2. Clear space
        res_clear = svc.update_professor_space(db_session, "CS101", None)
        assert res_clear["google_chat_space"] is None
        assert res_clear["is_configured"] is False

        # 3. Subject not found raises KeyError
        with pytest.raises(KeyError):
            svc.update_professor_space(db_session, "INVALID_CODE", "spaces/X")

    def test_default_space_db_override_and_fallback(self, db_session: Session):
        """Verify default space prioritizes database setting over env settings."""
        s = Settings(google_chat_default_space="spaces/ENV_DEFAULT")
        svc = GoogleChatOAuthService(settings=s)

        # Initially falls back to ENV
        assert svc.get_effective_default_space(db_session) == "spaces/ENV_DEFAULT"

        # Update in DB
        svc.set_default_space(db_session, "spaces/DB_OVERRIDE")
        assert svc.get_effective_default_space(db_session) == "spaces/DB_OVERRIDE"

        # Clear in DB falls back to ENV
        svc.set_default_space(db_session, None)
        assert svc.get_effective_default_space(db_session) == "spaces/ENV_DEFAULT"

    def test_token_refresh_failure_does_not_leak_refresh_token(self):
        """Token refresh failure raises OAuthAuthenticationError without leaking secret refresh token."""
        secret_refresh_token = "secret_refresh_token_to_never_leak_xyz789"
        storage = InMemoryTokenStorage(
            initial_token=OAuthToken(
                access_token="expired_tok",
                refresh_token=secret_refresh_token,
                expires_at=time.time() - 100,
            )
        )
        mock_http = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Token has been expired or revoked.",
        }
        mock_http.post.return_value = mock_resp

        s = Settings(google_chat_client_id="cid", google_chat_client_secret="csec")
        svc = GoogleChatOAuthService(settings=s, token_storage=storage)
        svc.oauth_client._http_client = mock_http

        with pytest.raises(OAuthAuthenticationError) as exc_info:
            svc.oauth_client.get_valid_access_token()

        err_str = str(exc_info.value)
        assert "Token has been expired or revoked" in err_str
        assert secret_refresh_token not in err_str

    def test_secret_redaction_in_status(self):
        """Connection status never contains client_secret or token contents."""
        secret_key = "super_classified_secret_key_123"
        storage = InMemoryTokenStorage(
            initial_token=OAuthToken(
                access_token="super_secret_access_tok_456",
                refresh_token="super_secret_refresh_tok_789",
                expires_at=time.time() + 3600,
            )
        )
        s = Settings(google_chat_client_id="cid", google_chat_client_secret=secret_key)
        svc = GoogleChatOAuthService(settings=s, token_storage=storage)
        st = svc.get_connection_status()

        status_str = str(st)
        assert secret_key not in status_str
        assert "super_secret_access_tok_456" not in status_str
        assert "super_secret_refresh_tok_789" not in status_str

    def test_find_dm_space_success(self):
        mock_api = MagicMock()
        mock_api.find_direct_message.return_value = {
            "name": "spaces/DM_AAAA111",
            "type": "DIRECT_MESSAGE",
        }
        svc = GoogleChatOAuthService(api_client=mock_api)
        space = svc.find_dm_space("turing@university.edu")
        assert space == "spaces/DM_AAAA111"
        mock_api.find_direct_message.assert_called_once_with(user_email="turing@university.edu")

    def test_find_dm_space_empty_email_raises_value_error(self):
        svc = GoogleChatOAuthService()
        with pytest.raises(ValueError, match="Professor email must be provided"):
            svc.find_dm_space("   ")

    def test_find_dm_space_missing_name_in_response(self):
        mock_api = MagicMock()
        mock_api.find_direct_message.return_value = {}
        svc = GoogleChatOAuthService(api_client=mock_api)
        with pytest.raises(ValueError, match="unexpected response without space name"):
            svc.find_dm_space("turing@university.edu")

    def test_discover_professor_dm_updates_target_and_matching_subjects(
        self, db_session: Session, configured_subject: Subject
    ):
        # Create a second subject with the same professor email
        sub2 = Subject(code="CS102", name="Advanced Systems")
        db_session.add(sub2)
        db_session.flush()
        m2 = ProfessorMapping(
            subject_id=sub2.id,
            professor_name="Dr. Alan Turing",
            professor_email="turing@university.edu",
            google_chat_space=None,
        )
        db_session.add(m2)
        db_session.commit()

        mock_api = MagicMock()
        mock_api.find_direct_message.return_value = {"name": "spaces/DM_TURING_123"}
        svc = GoogleChatOAuthService(api_client=mock_api)

        result = svc.discover_professor_dm(
            db=db_session,
            professor_email="turing@university.edu",
            subject_code="CS101",
        )

        assert result["space"] == "spaces/DM_TURING_123"
        assert result["professor_email"] == "turing@university.edu"
        assert result["subject_code"] == "CS101"
        assert "CS101" in result["updated_subjects"]
        assert "CS102" in result["updated_subjects"]

        # Verify DB records updated
        db_session.refresh(configured_subject.professor_mapping)
        db_session.refresh(m2)
        assert configured_subject.professor_mapping.google_chat_space == "spaces/DM_TURING_123"
        assert m2.google_chat_space == "spaces/DM_TURING_123"

    def test_discover_professor_dm_invalid_subject_code(self, db_session: Session):
        mock_api = MagicMock()
        svc = GoogleChatOAuthService(api_client=mock_api)
        with pytest.raises(KeyError, match="not found"):
            svc.discover_professor_dm(
                db=db_session,
                professor_email="turing@university.edu",
                subject_code="NONEXISTENT",
            )

    def test_discover_professor_dm_subject_without_mapping(self, db_session: Session):
        sub = Subject(code="CS999", name="No Prof Subject")
        db_session.add(sub)
        db_session.commit()

        mock_api = MagicMock()
        svc = GoogleChatOAuthService(api_client=mock_api)
        with pytest.raises(ValueError, match="does not have a professor assigned"):
            svc.discover_professor_dm(
                db=db_session,
                professor_email="prof@uni.edu",
                subject_code="CS999",
            )

    def test_discover_and_update_professor_space_from_mapping(
        self, db_session: Session, configured_subject: Subject
    ):
        mock_api = MagicMock()
        mock_api.find_direct_message.return_value = {"name": "spaces/DM_FOUND_1"}
        svc = GoogleChatOAuthService(api_client=mock_api)

        res = svc.discover_and_update_professor_space(db=db_session, subject_code="CS101")
        assert res["space"] == "spaces/DM_FOUND_1"
        assert res["professor_email"] == "turing@university.edu"

        db_session.refresh(configured_subject.professor_mapping)
        assert configured_subject.professor_mapping.google_chat_space == "spaces/DM_FOUND_1"

    def test_discover_and_update_professor_space_override_email(
        self, db_session: Session, configured_subject: Subject
    ):
        mock_api = MagicMock()
        mock_api.find_direct_message.return_value = {"name": "spaces/DM_OVERRIDE"}
        svc = GoogleChatOAuthService(api_client=mock_api)

        res = svc.discover_and_update_professor_space(
            db=db_session,
            subject_code="CS101",
            professor_email="alternate@university.edu",
        )
        assert res["space"] == "spaces/DM_OVERRIDE"
        assert res["professor_email"] == "alternate@university.edu"
        db_session.refresh(configured_subject.professor_mapping)
        assert configured_subject.professor_mapping.google_chat_space == "spaces/DM_OVERRIDE"

    def test_discover_and_update_professor_space_subject_not_found(self, db_session: Session):
        svc = GoogleChatOAuthService()
        with pytest.raises(KeyError, match="not found"):
            svc.discover_and_update_professor_space(db=db_session, subject_code="UNKNOWN")

    def test_discover_and_update_professor_space_no_email(self, db_session: Session):
        sub = Subject(code="CS888", name="Empty Prof")
        db_session.add(sub)
        db_session.commit()
        svc = GoogleChatOAuthService()
        with pytest.raises(ValueError, match="does not have a professor email configured"):
            svc.discover_and_update_professor_space(db=db_session, subject_code="CS888")

