"""Unit tests for AuditService, SQLite concurrency, and lock resilience."""

import sqlite3
import time
from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.enums import AuditEventType
from app.models.audit_event import AuditEvent
from app.services.audit import AuditService


class TestAuditService:
    def test_log_creates_and_persists_event(self, db_session: Session):
        service = AuditService(db=db_session)
        event = service.log(
            event_type=AuditEventType.ATTENDANCE_CHECK,
            action="SCHEDULER_START",
            entity_type="attendance_checks",
            run_id="run-123",
            details={"date": "2026-09-30", "apiKey": "secret_api_key_12345"},
        )

        assert event.id is not None
        assert event.run_id == "run-123"
        assert event.action == "SCHEDULER_START"
        # Secret should be redacted
        assert event.details.get("apiKey") == "[REDACTED]"

    def test_log_retries_on_transient_sqlite_lock_and_succeeds(self, db_session: Session):
        """When SQLite raises a transient 'database is locked', service rolls back and retries."""
        service = AuditService(db=db_session)

        mock_db = MagicMock(spec=Session)
        # First commit raises database is locked, second commit succeeds
        lock_error = OperationalError(
            "statement", {}, sqlite3.OperationalError("database is locked")
        )
        mock_db.commit.side_effect = [lock_error, None]

        service_with_mock = AuditService(db=mock_db)

        with patch("time.sleep", return_value=None) as mock_sleep:
            event = service_with_mock.log(
                event_type=AuditEventType.ATTENDANCE_CHECK,
                action="SCHEDULER_START",
                entity_type="attendance_checks",
                run_id="retry-run-1",
            )

        assert event is not None
        assert mock_db.commit.call_count == 2
        assert mock_db.rollback.call_count == 1
        mock_sleep.assert_called_once()

    def test_log_raises_when_retries_exhausted_on_database_lock(self):
        """When SQLite lock persists beyond max retries, exception is re-raised (not hidden)."""
        mock_db = MagicMock(spec=Session)
        lock_error = OperationalError(
            "statement", {}, sqlite3.OperationalError("database is locked")
        )
        mock_db.commit.side_effect = lock_error

        service = AuditService(db=mock_db)

        with patch("time.sleep", return_value=None):
            with pytest.raises(OperationalError) as exc_info:
                service.log(
                    event_type=AuditEventType.ATTENDANCE_CHECK,
                    action="SCHEDULER_START",
                    entity_type="attendance_checks",
                )

        assert "database is locked" in str(exc_info.value)
        assert mock_db.commit.call_count == 3
        assert mock_db.rollback.call_count == 3

    def test_get_events_filters_correctly(self, db_session: Session):
        service = AuditService(db=db_session)
        service.log(
            event_type=AuditEventType.ATTENDANCE_CHECK,
            action="CHECK_1",
            entity_type="attendance_checks",
            run_id="run-aaa",
        )
        service.log(
            event_type=AuditEventType.NOTIFICATION,
            action="NOTIF_1",
            entity_type="notifications",
            run_id="run-bbb",
        )

        check_events = service.get_events(run_id="run-aaa")
        assert len(check_events) == 1
        assert check_events[0].action == "CHECK_1"

        notif_events = service.get_events(event_type=AuditEventType.NOTIFICATION)
        assert len(notif_events) == 1
        assert notif_events[0].action == "NOTIF_1"
