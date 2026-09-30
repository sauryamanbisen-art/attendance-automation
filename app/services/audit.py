import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.enums import AuditEventType
from app.models.audit_event import AuditEvent
from app.security.redaction import redact_data

logger = logging.getLogger(__name__)


class AuditService:
    """Service responsible for recording and querying audit logs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def log(
        self,
        event_type: AuditEventType,
        action: str,
        entity_type: str,
        run_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """Create and persist an audit event with automated secret redaction.

        Features safe transaction rollback and bounded retry for transient SQLite database locks.
        """
        now = datetime.now(timezone.utc)
        safe_details = redact_data(details or {})

        event = AuditEvent(
            run_id=run_id or str(uuid.uuid4()),
            event_type=event_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=safe_details,
            timestamp=now,
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.db.add(event)
                self.db.commit()
                self.db.refresh(event)
                return event
            except (OperationalError, sqlite3.OperationalError) as exc:
                self.db.rollback()
                err_msg = str(exc).lower()
                is_lock = "locked" in err_msg or "busy" in err_msg
                if is_lock and attempt < max_retries - 1:
                    wait_time = 0.2 * (attempt + 1)
                    logger.warning(
                        "Audit log commit hit database lock on action=%s (attempt %d/%d). Retrying in %.1fs...",
                        action,
                        attempt + 1,
                        max_retries,
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue
                logger.error("Audit log failed to commit for action=%s: %s", action, exc)
                raise
            except SQLAlchemyError as exc:
                self.db.rollback()
                logger.error("Audit log failed with SQLAlchemy error for action=%s: %s", action, exc)
                raise

    def get_events(
        self,
        run_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AuditEvent]:
        """Query audit log history ordered by latest first."""
        query = self.db.query(AuditEvent)
        if run_id:
            query = query.filter(AuditEvent.run_id == run_id)
        if event_type:
            query = query.filter(AuditEvent.event_type == event_type)

        return (
            query.order_by(AuditEvent.timestamp.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
