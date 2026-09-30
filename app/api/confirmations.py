"""Daily attendance confirmation API endpoints: 'I WENT TO COLLEGE'."""

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import ConfirmationCreate, ConfirmationResponse
from app.database import get_db
from app.services.confirmation import ConfirmationService

router = APIRouter(prefix="/confirmations", tags=["Attendance Confirmation"])


@router.post("", response_model=ConfirmationResponse, status_code=status.HTTP_200_OK)
def confirm_daily_attendance(
    payload: ConfirmationCreate,
    db: Session = Depends(get_db),
) -> ConfirmationResponse:
    """Explicitly confirm attendance for a specific date: 'I WENT TO COLLEGE'.

    This operation is strictly date-specific and idempotent.
    """
    service = ConfirmationService(db)
    record, created = service.confirm_attendance(
        target_date=payload.date,
        note=payload.note,
    )
    return ConfirmationResponse(
        id=record.id,
        date=record.date,
        confirmed_at=record.confirmed_at,
        note=record.note,
        created=created,
    )


@router.get("/{target_date}", response_model=ConfirmationResponse)
def get_confirmation_for_date(
    target_date: date_type,
    db: Session = Depends(get_db),
) -> ConfirmationResponse:
    """Check if attendance has been explicitly confirmed for a given date."""
    service = ConfirmationService(db)
    record = service.get_confirmation(target_date)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attendance not confirmed for date {target_date}",
        )
    return ConfirmationResponse(
        id=record.id,
        date=record.date,
        confirmed_at=record.confirmed_at,
        note=record.note,
        created=False,
    )
