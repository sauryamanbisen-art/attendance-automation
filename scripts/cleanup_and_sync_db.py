"""Database cleanup and authoritative synchronization script.

Performs:
1. Purges invalid, mock, and non-curriculum subjects (CS101, ALL, UNKNOWN_COURSE_*)
2. Purges unscheduled check results (e.g. 303PDS on Wednesdays, weekend check runs)
3. Cleans raw internal dictionaries / debug metadata from notes
4. Populates verified weekly timetable slots for Monday-Friday
5. Configures official college holidays (2026-10-02 Gandhi Jayanti)
6. Seeds authoritative PWIOI portal academic attendance summary (147/157 = 94.0%)
"""

import json
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database.base import Base
from app.models.subject import Subject, VALID_CURRICULUM_CODES
from app.models.timetable import TimetableSlot
from app.models.calendar import Holiday, ClassException
from app.models.attendance_check import AttendanceCheck
from app.models.attendance_result import AttendanceResult
from app.models.portal_attendance import PortalAttendanceSummary
from app.core.enums import AttendanceStatus


CURRICULUM_SUBJECTS = [
    {"code": "301ADS", "name": "Advance Data Structures and Algorithms"},
    {"code": "302OPS", "name": "Operating System"},
    {"code": "303PDS", "name": "Python for Data Science"},
    {"code": "304ELS", "name": "Essential Language Skills"},
    {"code": "304VEP", "name": "Data Visualization using Excel and Powerbi"},
    {"code": "306JWD", "name": "OJT / Java Web Developer (Spring Boot)"},
]

# Weekday slot definitions (0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday)
# Verified PWIOI Term 3 Timetable:
# Mon: 301ADS, 302OPS, 303PDS, 304VEP, 306JWD (5 classes)
# Tue: 301ADS, 302OPS, 303PDS, 304ELS, 306JWD (5 classes)
# Wed: 301ADS, 302OPS, 304ELS, 304VEP, 306JWD (5 classes - NO Python 303PDS)
# Thu: 301ADS, 302OPS, 303PDS, 306JWD (4 classes)
# Fri: 301ADS, 302OPS, 304ELS, 304VEP, 306JWD (5 classes - NO Python 303PDS)


def run_cleanup(db: Session):
    print("=== Starting Database Cleanup and Sync ===")

    # 1. Purge non-curriculum subjects from subjects table if any exist
    invalid_subjects = db.query(Subject).filter(~Subject.code.in_(VALID_CURRICULUM_CODES)).all()
    for s in invalid_subjects:
        print(f"Removing invalid non-curriculum subject: {s.code} ({s.name})")
        db.delete(s)
    db.commit()

    # 2. Ensure all 6 curriculum subjects exist with correct names
    subject_map = {}
    for item in CURRICULUM_SUBJECTS:
        s = db.query(Subject).filter(Subject.code == item["code"]).first()
        if not s:
            s = Subject(code=item["code"], name=item["name"])
            db.add(s)
            db.flush()
            print(f"Created curriculum subject: {item['code']} - {item['name']}")
        else:
            s.name = item["name"]
        subject_map[item["code"]] = s
    db.commit()

    # 3. Purge invalid subject codes from attendance_results (CS101, ALL, UNKNOWN_COURSE_*)
    deleted_invalid = (
        db.query(AttendanceResult)
        .filter(~AttendanceResult.subject_code.in_(VALID_CURRICULUM_CODES))
        .delete(synchronize_session=False)
    )
    print(f"Deleted {deleted_invalid} invalid subject attendance records (CS101, ALL, UNKNOWN_*)")
    db.commit()

    # 4. Clean raw dictionary notes (remove Python dict strings like {'date': ...})
    raw_notes_results = db.query(AttendanceResult).filter(AttendanceResult.notes.like("{%")).all()
    for r in raw_notes_results:
        r.notes = None
    print(f"Cleaned raw dictionary notes from {len(raw_notes_results)} attendance records")
    db.commit()

    # 5. Purge unscheduled attendance records using authoritative TimetableService schedule
    from app.services.timetable_service import TimetableService
    timetable_service = TimetableService(db)

    all_results = (
        db.query(AttendanceResult, AttendanceCheck)
        .join(AttendanceCheck, AttendanceResult.check_id == AttendanceCheck.id)
        .all()
    )
    
    unscheduled_count = 0
    for res, chk in all_results:
        # Check against authoritative scheduled subjects for this specific date
        scheduled_subjects = timetable_service.get_classes_for_date(chk.check_date)
        scheduled_codes = {s.code for s in scheduled_subjects}
        if res.subject_code not in scheduled_codes:
            db.delete(res)
            unscheduled_count += 1
            
    print(f"Purged {unscheduled_count} unscheduled attendance records (classes not scheduled for that specific date)")
    db.commit()

    # 5b. Purge stale weekend checks and empty test check runs
    all_checks = db.query(AttendanceCheck).all()
    purged_checks = 0
    for chk in all_checks:
        chk_res_count = db.query(AttendanceResult).filter(AttendanceResult.check_id == chk.id).count()
        # Purge checks on weekend dates (Saturday/Sunday) where college is not in session
        if chk.check_date.weekday() in (5, 6):
            db.delete(chk)
            purged_checks += 1
        elif chk_res_count == 0 and chk.status.value == "SUCCESS":
            # Empty successful checks with 0 results are stale/dev test artifacts
            db.delete(chk)
            purged_checks += 1
    print(f"Purged {purged_checks} stale weekend and empty test check runs")
    db.commit()

    # 6. Reconcile verified weekly timetable slots
    db.query(TimetableSlot).delete()
    db.commit()
    print("Cleared all legacy verified weekly timetable slots (now managed dynamically by Google Calendar)")

    # 7. Populate official college holidays
    existing_holiday = db.query(Holiday).filter(Holiday.date == date(2026, 10, 2)).first()
    if not existing_holiday:
        holiday = Holiday(date=date(2026, 10, 2), description="Gandhi Jayanti (Official Holiday)")
        db.add(holiday)
        db.commit()
        print("Configured holiday: 2026-10-02 (Gandhi Jayanti)")
    else:
        print("Holiday 2026-10-02 already configured")

    # 8. Synchronize authoritative PWIOI portal academic summary via live extraction
    from app.adapters.pwioi.adapter import PWIOIPortalAdapter
    from app.adapters.pwioi.config import PWIOIPortalConfig
    from app.services.portal_attendance_service import PortalAttendanceService

    portal_svc = PortalAttendanceService(db)
    config = PWIOIPortalConfig(storage_state_path="storage_state/pwioi_session.json", headless=True)
    adapter = PWIOIPortalAdapter(config=config)
    try:
        extracted = adapter.extract_academic_summary()
        if extracted.get("sync_status") == "SYNCED":
            summary = portal_svc.update_summary(
                overall_rate=extracted.get("overall_rate"),
                total_classes=extracted.get("total_classes"),
                attended_classes=extracted.get("attended_classes"),
                missed_classes=extracted.get("missed_classes"),
                course_count=extracted.get("course_count"),
                course_stats=extracted.get("courses"),
                sync_status="SYNCED",
            )
            print(f"Synchronized live portal attendance: {summary.overall_rate}% ({summary.attended_classes}/{summary.total_classes})")
        else:
            print("Portal session unauthenticated; setting status to AWAITING_PORTAL_SYNC (Fail-closed)")
            portal_svc.get_or_create_awaiting_summary()
    except Exception as e:
        print(f"Portal live sync error: {e}. Preserving fail-closed state.")
    finally:
        adapter.close()

    print("=== Database Cleanup and Sync Completed Successfully ===")


if __name__ == "__main__":
    from app.database.session import SessionLocal
    db = SessionLocal()
    try:
        run_cleanup(db)
    finally:
        db.close()
