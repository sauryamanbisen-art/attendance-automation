"""API endpoints for managing holidays and class exceptions."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    ClassExceptionCreate,
    ClassExceptionResponse,
    HolidayCreate,
    HolidayResponse,
)
from app.database.session import get_db
from app.models.calendar import ClassException, ExceptionType, Holiday
from app.models.subject import Subject

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/holidays", response_model=List[HolidayResponse])
def list_holidays(db: Session = Depends(get_db)):
    """List all holidays."""
    return db.query(Holiday).all()


@router.post("/holidays", response_model=HolidayResponse, status_code=201)
def create_holiday(holiday_in: HolidayCreate, db: Session = Depends(get_db)):
    """Create a new holiday."""
    existing = db.query(Holiday).filter(Holiday.date == holiday_in.date).first()
    if existing:
        raise HTTPException(status_code=400, detail="Holiday already exists on this date")

    holiday = Holiday(**holiday_in.model_dump())
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


@router.delete("/holidays/{holiday_id}", status_code=204)
def delete_holiday(holiday_id: int, db: Session = Depends(get_db)):
    """Delete a holiday."""
    holiday = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")

    db.delete(holiday)
    db.commit()
    return None


@router.get("/exceptions", response_model=List[ClassExceptionResponse])
def list_exceptions(db: Session = Depends(get_db)):
    """List all class exceptions."""
    return db.query(ClassException).all()


@router.post("/exceptions", response_model=ClassExceptionResponse, status_code=201)
def create_exception(exception_in: ClassExceptionCreate, db: Session = Depends(get_db)):
    """Create a class exception."""
    subject = db.query(Subject).filter(Subject.id == exception_in.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    if exception_in.start_time and exception_in.end_time:
        if exception_in.start_time >= exception_in.end_time:
            raise HTTPException(status_code=400, detail="start_time must be before end_time")

    # Check for existing exceptions on this date for this subject
    existing_exceptions = (
        db.query(ClassException)
        .filter(
            ClassException.subject_id == exception_in.subject_id,
            ClassException.date == exception_in.date,
        )
        .all()
    )
    for existing in existing_exceptions:
        if existing.exception_type == exception_in.exception_type:
            raise HTTPException(
                status_code=400,
                detail=f"A {exception_in.exception_type.value} exception already exists for this subject on this date",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot add {exception_in.exception_type.value} exception because a conflicting {existing.exception_type.value} exception exists for this subject on this date",
            )

    exc = ClassException(**exception_in.model_dump())
    db.add(exc)
    db.commit()
    db.refresh(exc)
    return exc


@router.delete("/exceptions/{exception_id}", status_code=204)
def delete_exception(exception_id: int, db: Session = Depends(get_db)):
    """Delete a class exception."""
    exc = db.query(ClassException).filter(ClassException.id == exception_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Class exception not found")

    db.delete(exc)
    db.commit()
    return None
