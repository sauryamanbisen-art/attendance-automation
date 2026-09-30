"""Audit log inquiry endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import AuditEventResponse
from app.core.enums import AuditEventType
from app.database import get_db
from app.services.audit import AuditService

router = APIRouter(prefix="/audit", tags=["Audit Log"])


@router.get("", response_model=List[AuditEventResponse])
def get_audit_logs(
    run_id: Optional[str] = Query(None, description="Filter by run UUID"),
    event_type: Optional[AuditEventType] = Query(None, description="Filter by event category"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> List[AuditEventResponse]:
    """Retrieve chronologically ordered audit logs."""
    service = AuditService(db)
    events = service.get_events(
        run_id=run_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return [
        AuditEventResponse(
            id=e.id,
            run_id=e.run_id,
            event_type=e.event_type.value,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            details=e.details,
            timestamp=e.timestamp,
        )
        for e in events
    ]
