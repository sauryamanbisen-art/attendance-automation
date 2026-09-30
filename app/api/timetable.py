"""API endpoints for managing the regular weekly timetable."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import TimetableSlotCreate, TimetableSlotResponse
from app.database.session import get_db
from app.models.subject import Subject
from app.models.timetable import TimetableSlot

router = APIRouter(prefix="/timetable", tags=["timetable"])


@router.get("/", response_model=List[TimetableSlotResponse])
def list_slots(db: Session = Depends(get_db)):
    """List all timetable slots."""
    return db.query(TimetableSlot).all()


@router.post("/", response_model=TimetableSlotResponse, status_code=201)
def create_slot(slot_in: TimetableSlotCreate, db: Session = Depends(get_db)):
    """Create a new timetable slot."""
    subject = db.query(Subject).filter(Subject.id == slot_in.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    if slot_in.start_time >= slot_in.end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    if slot_in.valid_from and slot_in.valid_to and slot_in.valid_from > slot_in.valid_to:
        raise HTTPException(status_code=400, detail="valid_from cannot be after valid_to")

    slot = TimetableSlot(**slot_in.model_dump())
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


@router.put("/{slot_id}", response_model=TimetableSlotResponse)
def update_slot(slot_id: int, slot_in: TimetableSlotCreate, db: Session = Depends(get_db)):
    """Update an existing timetable slot."""
    slot = db.query(TimetableSlot).filter(TimetableSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Timetable slot not found")

    subject = db.query(Subject).filter(Subject.id == slot_in.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    if slot_in.start_time >= slot_in.end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    if slot_in.valid_from and slot_in.valid_to and slot_in.valid_from > slot_in.valid_to:
        raise HTTPException(status_code=400, detail="valid_from cannot be after valid_to")

    update_data = slot_in.model_dump()
    for field, value in update_data.items():
        setattr(slot, field, value)

    db.commit()
    db.refresh(slot)
    return slot


@router.delete("/{slot_id}", status_code=204)
def delete_slot(slot_id: int, db: Session = Depends(get_db)):
    """Delete a timetable slot."""
    slot = db.query(TimetableSlot).filter(TimetableSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Timetable slot not found")

    db.delete(slot)
    db.commit()
    return None
