"""Attendance check execution and decision evaluation endpoints."""

import uuid
from datetime import date, datetime, timezone
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.adapters import get_portal_adapter
from app.adapters.fake.adapter import FakeScenario
from app.api.history import sanitize_note
from app.api.schemas import CheckRunRequest, CheckRunResponse, DecisionItem, SubjectResultItem
from app.config import get_settings
from app.core.enums import AttendanceStatus, AuditEventType, CheckStatus
from app.database import get_db
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_result import AttendanceResult
from app.models.subject import Subject, is_valid_curriculum_code
from app.models.timetable import TimetableSlot
from app.security.redaction import redact_string
from app.services.audit import AuditService
from app.services.decision_engine import DecisionEngine
from app.services.timetable_service import TimetableService

router = APIRouter(prefix="/checks", tags=["Attendance Checks"])


@router.post("/run", response_model=CheckRunResponse)
def run_attendance_check(
    payload: CheckRunRequest = CheckRunRequest(),
    db: Session = Depends(get_db),
) -> CheckRunResponse:
    """Execute an attendance check against the configured portal adapter and evaluate decisions."""
    settings = get_settings()
    audit_service = AuditService(db)
    decision_engine = DecisionEngine()

    target_date = payload.date or date.today()
    run_id = str(uuid.uuid4())

    
    # Schedule resolution and timetable gating
    timetable_service = TimetableService(db)
    is_holiday = timetable_service.is_holiday(target_date)
    try:
        scheduled_classes = timetable_service.get_classes_for_date(target_date)
    except Exception as e:
        logger.error(f"Failed to fetch schedule in manual check: {e}")
        check_record = AttendanceCheck(
            run_id=run_id,
            check_date=target_date,
            checked_at=datetime.now(timezone.utc),
            adapter_name="scheduled_calendar",
            status=CheckStatus.FAILED,
            error_message=str(e),
        )
        db.add(check_record)
        db.commit()
        return CheckRunResponse(
            run_id=run_id,
            check_date=target_date,
            adapter_name="scheduled_calendar",
            status=CheckStatus.FAILED,
            results=[],
            decisions=[],
            error_message=str(e),
        )

    expected_subject_codes = {}
    
    tz_name = settings.timezone or "Asia/Kolkata"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
        
    now_dt = datetime.now(tz)
    current_date = now_dt.date()
    current_time = now_dt.time()
    
    for c in scheduled_classes:
        if is_valid_curriculum_code(c.subject.code):
            # Never evaluate a class before its scheduled end time
            if target_date == current_date and c.end_time > current_time:
                continue
            expected_subject_codes[c.subject.code] = c.subject

    if len(expected_subject_codes) == 0:
        # When 0 classes are scheduled for this date or all classes are in the future
        check_record = AttendanceCheck(
            run_id=run_id,
            check_date=target_date,
            checked_at=datetime.now(timezone.utc),
            adapter_name="scheduled_calendar",
            status=CheckStatus.SUCCESS,
            error_message=None,
        )
        db.add(check_record)
        db.commit()
        return CheckRunResponse(
            run_id=run_id,
            check_date=target_date,
            adapter_name="scheduled_calendar",
            status=CheckStatus.SUCCESS,
            results=[],
            decisions=[],
        )


    # Instantiate adapter via factory (respects scenario override or configured adapter)
    adapter = get_portal_adapter(
        settings=settings,
        scenario=payload.scenario,
    )
    adapter_name = adapter.adapter_name

    check_record = AttendanceCheck(
        run_id=run_id,
        check_date=target_date,
        checked_at=datetime.now(timezone.utc),
        adapter_name=adapter_name,
        status=CheckStatus.SUCCESS,
        error_message=None,
    )
    db.add(check_record)
    db.flush()

    results_items: List[SubjectResultItem] = []
    decision_items: List[DecisionItem] = []
    processed_codes = set()

    try:
        adapter.validate_config()
        adapter.authenticate()
        records = adapter.get_attendance_for_date(target_date)

        for rec in records:
            # Gating Rule 1: Non-curriculum codes (e.g. CS101, ALL) are ignored
            if not is_valid_curriculum_code(rec.subject_code):
                continue

            # Gating Rule 2: Unscheduled classes for this date are ignored
            if rec.subject_code not in expected_subject_codes:
                continue

            # Gating Rule 3: Deduplicate by subject code so 5 classes cannot become 6
            if rec.subject_code in processed_codes:
                continue

            processed_codes.add(rec.subject_code)
            # Find or link subject if exists
            subject = db.query(Subject).filter(Subject.code == rec.subject_code).first()
            subject_id = subject.id if subject else None

            # Clean human-readable note only; never serialize raw debug dict
            clean_note = None
            if rec.metadata and isinstance(rec.metadata, dict):
                raw_n = rec.metadata.get("note") or rec.metadata.get("description")
                if raw_n and isinstance(raw_n, str) and not raw_n.strip().startswith("{"):
                    clean_note = raw_n.strip()
            elif isinstance(rec.metadata, str) and not rec.metadata.strip().startswith("{"):
                clean_note = rec.metadata.strip()

            res_record = AttendanceResult(
                check_id=check_record.id,
                subject_id=subject_id,
                subject_code=rec.subject_code,
                status=rec.status,
                raw_status=rec.raw_status,
                is_reliable=rec.is_reliable,
                notes=clean_note,
            )
            db.add(res_record)
            results_items.append(
                SubjectResultItem(
                    subject_code=rec.subject_code,
                    status=rec.status,
                    raw_status=rec.raw_status,
                    is_reliable=rec.is_reliable,
                )
            )

            # Evaluate decision engine safety rules
            dec = decision_engine.evaluate_subject_record(
                db=db,
                target_date=target_date,
                subject_code=rec.subject_code,
                status=rec.status,
                is_reliable=rec.is_reliable,
            )
            decision_items.append(
                DecisionItem(
                    action=dec.action,
                    reason=dec.reason,
                    subject_code=dec.subject_code,
                    target_date=dec.target_date,
                    is_confirmed=dec.is_confirmed,
                    status=dec.status,
                    is_reliable=dec.is_reliable,
                    professor_email=dec.professor_email,
                )
            )

        # Evaluate expected scheduled classes missing from portal response
        for code, subject in expected_subject_codes.items():
            if code not in processed_codes:
                res_record = AttendanceResult(
                    check_id=check_record.id,
                    subject_id=subject.id,
                    subject_code=code,
                    status=AttendanceStatus.UNKNOWN,
                    raw_status="MISSING_FROM_PORTAL",
                    is_reliable=False,
                    notes="Expected from timetable but missing from portal response",
                )
                db.add(res_record)
                results_items.append(
                    SubjectResultItem(
                        subject_code=code,
                        status=AttendanceStatus.UNKNOWN,
                        raw_status="MISSING_FROM_PORTAL",
                        is_reliable=False,
                    )
                )
                dec = decision_engine.evaluate_subject_record(
                    db=db,
                    target_date=target_date,
                    subject_code=code,
                    status=AttendanceStatus.UNKNOWN,
                    is_reliable=False,
                )
                decision_items.append(
                    DecisionItem(
                        action=dec.action,
                        reason=dec.reason,
                        subject_code=dec.subject_code,
                        target_date=dec.target_date,
                        is_confirmed=dec.is_confirmed,
                        status=dec.status,
                        is_reliable=dec.is_reliable,
                        professor_email=dec.professor_email,
                    )
                )

        db.commit()

        # Audit log the check execution
        audit_service.log(
            event_type=AuditEventType.ATTENDANCE_CHECK,
            action="RUN_ATTENDANCE_CHECK",
            entity_type="attendance_checks",
            run_id=run_id,
            entity_id=str(check_record.id),
            details={
                "date": target_date.isoformat(),
                "adapter": adapter_name,
                "subjects_checked": len(decision_items),
                "decisions": [
                    {
                        "code": d.subject_code,
                        "action": d.action,
                        "reason": d.reason,
                        "status": d.status,
                        "is_reliable": d.is_reliable,
                    }
                    for d in decision_items
                ],
            },
        )

        return CheckRunResponse(
            run_id=run_id,
            check_date=target_date,
            adapter_name=adapter_name,
            status=CheckStatus.SUCCESS,
            results=results_items,
            decisions=decision_items,
        )

    except Exception as exc:
        db.rollback()
        safe_error = redact_string(str(exc))
        check_record.status = CheckStatus.FAILED
        check_record.error_message = safe_error
        db.add(check_record)
        db.commit()

        audit_service.log(
            event_type=AuditEventType.ATTENDANCE_CHECK,
            action="CHECK_FAILED",
            entity_type="attendance_checks",
            run_id=run_id,
            entity_id=str(check_record.id),
            details={"error": safe_error, "date": target_date.isoformat()},
        )

        return CheckRunResponse(
            run_id=run_id,
            check_date=target_date,
            adapter_name=adapter_name,
            status=CheckStatus.FAILED,
            results=[],
            decisions=[],
            error_message=safe_error,
        )
    finally:
        adapter.close()


@router.get("/latest")
def get_latest_check(db: Session = Depends(get_db)):
    """Retrieve the most recent attendance check run strictly gated against verified schedule."""
    check = (
        db.query(AttendanceCheck)
        .order_by(AttendanceCheck.checked_at.desc())
        .first()
    )
    if not check:
        return {"check": None}

    has_configured_slots = db.query(TimetableSlot).count() > 0
    scheduled_codes = None
    if has_configured_slots:
        scheduled_subjects = TimetableService(db).get_classes_for_date(check.check_date)
        scheduled_codes = {s.code for s in scheduled_subjects if is_valid_curriculum_code(s.code)}

    results = []
    seen_codes = set()
    for r in check.results:
        if not is_valid_curriculum_code(r.subject_code):
            continue
        if scheduled_codes is not None and r.subject_code not in scheduled_codes:
            continue
        if r.subject_code in seen_codes:
            continue
        seen_codes.add(r.subject_code)

        subject_name = r.subject.name if r.subject else r.subject_code
        prof_name = (
            r.subject.professor_mapping.professor_name
            if r.subject and r.subject.professor_mapping
            else None
        )
        results.append({
            "subject_code": r.subject_code,
            "subject_name": subject_name,
            "professor_name": prof_name,
            "status": r.status.value,
            "raw_status": r.raw_status,
            "is_reliable": r.is_reliable,
            "notes": sanitize_note(r.notes),
        })

    return {
        "check": {
            "id": check.id,
            "run_id": check.run_id,
            "date": check.check_date.isoformat(),
            "checked_at": check.checked_at.isoformat(),
            "adapter_name": check.adapter_name,
            "status": check.status.value,
            "error_message": check.error_message,
            "results": results,
        }
    }


@router.get("/recent")
def get_recent_checks(
    limit: int = 5,
    db: Session = Depends(get_db),
):
    """Retrieve recent attendance check runs strictly gated against verified schedule."""
    checks = (
        db.query(AttendanceCheck)
        .order_by(AttendanceCheck.checked_at.desc())
        .limit(limit)
        .all()
    )
    timetable_svc = TimetableService(db)
    has_configured_slots = db.query(TimetableSlot).count() > 0

    date_scheduled_map = {}
    data = []
    for check in checks:
        if has_configured_slots:
            if check.check_date not in date_scheduled_map:
                scheduled = timetable_svc.get_classes_for_date(check.check_date)
                date_scheduled_map[check.check_date] = {s.code for s in scheduled if is_valid_curriculum_code(s.code)}
            scheduled_codes = date_scheduled_map[check.check_date]
        else:
            scheduled_codes = None

        results = []
        seen_codes = set()
        for r in check.results:
            if not is_valid_curriculum_code(r.subject_code):
                continue
            if scheduled_codes is not None and r.subject_code not in scheduled_codes:
                continue
            if r.subject_code in seen_codes:
                continue
            seen_codes.add(r.subject_code)

            subject_name = r.subject.name if r.subject else r.subject_code
            prof_name = (
                r.subject.professor_mapping.professor_name
                if r.subject and r.subject.professor_mapping
                else None
            )
            results.append({
                "subject_code": r.subject_code,
                "subject_name": subject_name,
                "professor_name": prof_name,
                "status": r.status.value,
                "raw_status": r.raw_status,
                "is_reliable": r.is_reliable,
                "notes": sanitize_note(r.notes),
            })

        data.append({
            "id": check.id,
            "run_id": check.run_id,
            "date": check.check_date.isoformat(),
            "checked_at": check.checked_at.isoformat(),
            "adapter_name": check.adapter_name,
            "status": check.status.value,
            "error_message": check.error_message,
            "results": results,
        })
    return data


@router.get("/notifications")
def get_recent_notifications(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Retrieve recent notification events."""
    from app.models.notification_event import NotificationEvent

    events = (
        db.query(NotificationEvent)
        .order_by(NotificationEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "date": e.date.isoformat(),
            "subject_code": e.subject_code,
            "subject_name": e.subject.name if e.subject else e.subject_code,
            "recipient_email": e.recipient_email,
            "status": e.status.value,
            "dry_run": e.dry_run,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "created_at": e.created_at.isoformat(),
            "error_message": e.error_message,
        }
        for e in events
    ]

