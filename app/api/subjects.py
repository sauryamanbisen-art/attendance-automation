"""Subject and professor mapping management endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import ProfessorMappingSchema, SubjectCreate, SubjectResponse
from app.database import get_db
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject

router = APIRouter(prefix="/subjects", tags=["Subjects & Mappings"])


@router.get("", response_model=List[SubjectResponse])
def list_subjects(db: Session = Depends(get_db)) -> List[SubjectResponse]:
    """List all configured subjects along with professor mappings."""
    from app.services.portal_attendance_service import PortalAttendanceService
    portal_svc = PortalAttendanceService(db)
    acad = portal_svc.get_summary()
    course_stats = acad.get_course_stats() if (acad and acad.sync_status == "SYNCED") else {}

    subjects = db.query(Subject).all()
    results = []
    for s in subjects:
        prof_name = s.professor_mapping.professor_name if s.professor_mapping else None
        prof_email = s.professor_mapping.professor_email if s.professor_mapping else None
        chat_space = s.professor_mapping.google_chat_space if s.professor_mapping else None
        is_active = s.professor_mapping.is_active if s.professor_mapping else None
        c_stat = course_stats.get(s.code, {})
        attended_val = c_stat.get("attended_classes") if c_stat.get("attended_classes") is not None else c_stat.get("attended")
        total_val = c_stat.get("total_classes") if c_stat.get("total_classes") is not None else c_stat.get("total")
        rate_val = c_stat.get("rate") if c_stat.get("rate") is not None else c_stat.get("attendance_rate")
        results.append(
            SubjectResponse(
                id=s.id,
                code=s.code,
                name=s.name,
                professor_name=prof_name,
                professor_email=prof_email,
                google_chat_space=chat_space,
                is_active=is_active,
                academic_rate=rate_val,
                attended_classes=attended_val,
                total_classes=total_val,
            )
        )
    return results


@router.post("", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
def create_subject(
    payload: SubjectCreate,
    db: Session = Depends(get_db),
) -> SubjectResponse:
    """Create a new subject and optionally link a professor mapping."""
    existing = db.query(Subject).filter(Subject.code == payload.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Subject with code '{payload.code}' already exists.",
        )

    subject = Subject(code=payload.code, name=payload.name)
    db.add(subject)
    db.flush()

    if payload.professor_name and payload.professor_email:
        is_active_val = payload.is_active if payload.is_active is not None else True
        mapping = ProfessorMapping(
            subject_id=subject.id,
            professor_name=payload.professor_name,
            professor_email=str(payload.professor_email),
            google_chat_space=payload.google_chat_space,
            is_active=is_active_val,
        )
        db.add(mapping)

    db.commit()
    db.refresh(subject)

    prof_name = subject.professor_mapping.professor_name if subject.professor_mapping else None
    prof_email = subject.professor_mapping.professor_email if subject.professor_mapping else None
    chat_space = subject.professor_mapping.google_chat_space if subject.professor_mapping else None
    is_active = subject.professor_mapping.is_active if subject.professor_mapping else None

    return SubjectResponse(
        id=subject.id,
        code=subject.code,
        name=subject.name,
        professor_name=prof_name,
        professor_email=prof_email,
        google_chat_space=chat_space,
        is_active=is_active,
    )


@router.post("/{code}/mapping", response_model=SubjectResponse)
def set_professor_mapping(
    code: str,
    payload: ProfessorMappingSchema,
    db: Session = Depends(get_db),
) -> SubjectResponse:
    """Set or update professor mapping for an existing subject."""
    subject = db.query(Subject).filter(Subject.code == code).first()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with code '{code}' not found.",
        )

    if subject.professor_mapping:
        subject.professor_mapping.professor_name = payload.professor_name
        subject.professor_mapping.professor_email = str(payload.professor_email)
        subject.professor_mapping.google_chat_space = payload.google_chat_space
        subject.professor_mapping.is_active = payload.is_active
    else:
        mapping = ProfessorMapping(
            subject_id=subject.id,
            professor_name=payload.professor_name,
            professor_email=str(payload.professor_email),
            google_chat_space=payload.google_chat_space,
            is_active=payload.is_active,
        )
        db.add(mapping)

    db.commit()
    db.refresh(subject)

    return SubjectResponse(
        id=subject.id,
        code=subject.code,
        name=subject.name,
        professor_name=subject.professor_mapping.professor_name,
        professor_email=subject.professor_mapping.professor_email,
        google_chat_space=subject.professor_mapping.google_chat_space,
        is_active=subject.professor_mapping.is_active,
    )


@router.put("/{code}", response_model=SubjectResponse)
def update_subject(
    code: str,
    payload: SubjectCreate,
    db: Session = Depends(get_db),
) -> SubjectResponse:
    """Update a subject and its professor mapping."""
    subject = db.query(Subject).filter(Subject.code == code).first()
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject '{code}' not found.")

    if code != payload.code:
        existing = db.query(Subject).filter(Subject.code == payload.code).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Subject '{payload.code}' already exists.")
        subject.code = payload.code

    subject.name = payload.name

    if payload.professor_name and payload.professor_email:
        is_active_val = payload.is_active if payload.is_active is not None else True
        if subject.professor_mapping:
            subject.professor_mapping.professor_name = payload.professor_name
            subject.professor_mapping.professor_email = str(payload.professor_email)
            subject.professor_mapping.google_chat_space = payload.google_chat_space
            subject.professor_mapping.is_active = is_active_val
        else:
            mapping = ProfessorMapping(
                subject_id=subject.id,
                professor_name=payload.professor_name,
                professor_email=str(payload.professor_email),
                google_chat_space=payload.google_chat_space,
                is_active=is_active_val,
            )
            db.add(mapping)
    elif subject.professor_mapping:
        db.delete(subject.professor_mapping)

    db.commit()
    db.refresh(subject)

    prof_name = subject.professor_mapping.professor_name if subject.professor_mapping else None
    prof_email = subject.professor_mapping.professor_email if subject.professor_mapping else None
    chat_space = subject.professor_mapping.google_chat_space if subject.professor_mapping else None
    is_active = subject.professor_mapping.is_active if subject.professor_mapping else None

    return SubjectResponse(
        id=subject.id,
        code=subject.code,
        name=subject.name,
        professor_name=prof_name,
        professor_email=prof_email,
        google_chat_space=chat_space,
        is_active=is_active,
    )


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(
    code: str,
    db: Session = Depends(get_db),
):
    """Delete a subject and its mapping."""
    subject = db.query(Subject).filter(Subject.code == code).first()
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject '{code}' not found.")

    # Due to cascade rules or manual cleanup, delete mapping if exists
    if subject.professor_mapping:
        db.delete(subject.professor_mapping)
    
    db.delete(subject)
    db.commit()
    return None
