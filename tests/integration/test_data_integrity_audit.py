"""Integration and Data Integrity Audit Tests.

Verifies:
1. Complete Data Source Audit across all endpoints.
2. Separation of Academic Attendance from Automation Execution Logs.
3. Realistic identity extraction from PWIOI portal storage state.
4. Truthful fallback states ('Awaiting Portal Sync', 'N/A') when portal is not yet synced.
5. Absence of synthetic or placeholder metrics across all responses.
"""

from fastapi.testclient import TestClient


def test_portal_summary_and_sync_endpoints(client: TestClient) -> None:
    """Verify /api/portal/summary endpoint returns truthful data model without fake values."""
    res = client.get("/api/portal/summary")
    assert res.status_code == 200
    data = res.json()
    assert "sync_status" in data
    assert data["sync_status"] in ["AWAITING_PORTAL_SYNC", "SUCCESS", "FAILED"]
    # When awaiting portal sync, overall_rate must be null, never synthetic 0% or fake 95%
    if data["sync_status"] == "AWAITING_PORTAL_SYNC":
        assert data["overall_rate"] is None
        assert data["total_classes"] is None
        assert data["attended_classes"] is None


def test_history_summary_strict_separation_of_concerns(client: TestClient) -> None:
    """Verify /api/history/summary strictly separates academic attendance from automation logs."""
    res = client.get("/api/history/summary")
    assert res.status_code == 200
    data = res.json()

    # 1. Academic attendance section
    assert "academic_attendance" in data
    acad = data["academic_attendance"]
    assert "sync_status" in acad
    assert "overall_rate" in acad
    assert "total_classes" in acad
    assert "attended_classes" in acad

    # 2. Automation logs section
    assert "automation_logs" in data
    auto = data["automation_logs"]
    assert "total_checks" in auto
    assert "total_log_records" in auto
    assert "check_reconciliation_rate" in auto
    assert "flagged_events" in auto

    # 3. Overall attendance_rate must be null when portal sync is awaiting (not synthetic check ratio)
    if acad["sync_status"] == "AWAITING_PORTAL_SYNC":
        assert data["attendance_rate"] is None


def test_dashboard_today_data_truthfulness(client: TestClient) -> None:
    """Verify /api/dashboard/today does not return synthetic attendance percentage."""
    res = client.get("/api/dashboard/today")
    assert res.status_code == 200
    data = res.json()

    assert "today" in data
    assert "is_confirmed" in data
    assert "academic_sync_status" in data
    if data["academic_sync_status"] == "AWAITING_PORTAL_SYNC":
        assert data["academic_attendance_rate"] is None
        assert data["academic_attended_classes"] is None
        assert data["academic_total_classes"] is None


def test_subjects_real_faculty_and_no_fake_attendance(client: TestClient) -> None:
    """Verify /api/subjects returns authentic courses with real faculty and null academic rate when unsynced."""
    # Seed the authentic PWIOI subjects
    sample_pwioi_subjects = [
        {"code": "304ELS", "name": "Essential Language Skills", "professor_name": "Gurminder Singh Bhamrah", "professor_email": "gurminder.bhamrah@pw.live", "google_chat_space": "spaces/AAQAsCjY__U"},
        {"code": "302OPS", "name": "Operating System", "professor_name": "Shubham Bansal", "professor_email": "shubham.bansal2@pw.live", "google_chat_space": "spaces/wADgDyAAAAE"},
        {"code": "301ADS", "name": "Advance Data Structures and Algorithms", "professor_name": "Prerit Saxena", "professor_email": "prerit.saxena@pw.live", "google_chat_space": "spaces/53ncfKAAAAE"},
        {"code": "306JWD", "name": "OJT / Java Web Developer (Spring Boot)", "professor_name": "Dharmaraj Thakaji Pawale", "professor_email": "dharmaraj.pawale@pw.live", "google_chat_space": "spaces/oPfSXSAAAAE"},
        {"code": "304VEP", "name": "Data Visualization using Excel and Powerbi", "professor_name": "Shubham Bansal", "professor_email": "shubham.bansal2@pw.live", "google_chat_space": "spaces/wADgDyAAAAE"},
        {"code": "303PDS", "name": "Python for Data Science", "professor_name": "Vishal Kumar Singh", "professor_email": "vishal.singh20@pw.live", "google_chat_space": "spaces/klLPaqAAAAE"}
    ]
    for sub in sample_pwioi_subjects:
        client.post("/api/subjects", json=sub)

    res = client.get("/api/subjects")
    assert res.status_code == 200
    subjects = res.json()

    assert len(subjects) >= 6
    codes = {s["code"] for s in subjects}
    assert {"301ADS", "302OPS", "303PDS", "304ELS", "304VEP", "306JWD"}.issubset(codes)

    for s in subjects:
        # Check faculty emails end in @pw.live or configured domain, never dummy @example.edu
        if s.get("professor_email"):
            assert not s["professor_email"].endswith("@example.edu"), f"Placeholder email found: {s['professor_email']}"
            assert "@" in s["professor_email"]
        
        # When awaiting portal sync, academic_rate must be None, not synthetic 0% or 100%
        assert "academic_rate" in s
        assert s["academic_rate"] is None
        assert s["attended_classes"] is None
        assert s["total_classes"] is None


def test_session_status_identity_extraction(client: TestClient) -> None:
    """Verify /api/settings/session returns authentic student identity from storage state."""
    res = client.get("/api/settings/session")
    assert res.status_code == 200
    data = res.json()

    assert "is_authenticated" in data
    assert "session_file_exists" in data
    if data["is_authenticated"]:
        assert data["student_name"] == "SAURYAMAN BISEN"
        assert data["student_email"] == "sauryaman.bisen.sot25@pwioi.com"
        assert data["enrollment_id"] == "2501040065"


def test_frontend_files_contain_safety_protections(client: TestClient) -> None:
    """Verify frontend JavaScript files contain development safety protections and comments."""
    for path in ["/static/js/pages/history.js", "/static/js/pages/subjects.js", "/static/js/pages/dashboard.js"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "Never display synthetic attendance information" in res.text


def test_invalid_subject_cs101_cannot_enter_history(client: TestClient, db_session) -> None:
    """Requirement 1: Invalid subject such as CS101 cannot enter current attendance history."""
    from datetime import date
    from app.core.enums import AttendanceStatus, CheckStatus
    from app.models.attendance_check import AttendanceCheck
    from app.models.attendance_result import AttendanceResult

    # Insert a check with both valid and invalid (CS101) records
    chk = AttendanceCheck(
        run_id="audit-test-run-1",
        check_date=date(2026, 9, 28),
        adapter_name="audit_test",
        status=CheckStatus.SUCCESS,
    )
    db_session.add(chk)
    db_session.flush()

    res_valid = AttendanceResult(
        check_id=chk.id,
        subject_code="301ADS",
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
    )
    res_invalid = AttendanceResult(
        check_id=chk.id,
        subject_code="CS101",
        status=AttendanceStatus.ABSENT,
        is_reliable=True,
    )
    db_session.add_all([res_valid, res_invalid])
    db_session.commit()

    # Query history API
    history_res = client.get("/api/history")
    assert history_res.status_code == 200
    items = history_res.json()["items"]
    codes = [item["subject_code"] for item in items]
    assert "CS101" not in codes
    assert "301ADS" in codes

    # Query summary API
    summary_res = client.get("/api/history/summary")
    assert summary_res.status_code == 200
    subj_stats = summary_res.json()["subject_stats"]
    assert "CS101" not in subj_stats


def test_unscheduled_python_class_cannot_generate_attendance(client: TestClient, db_session) -> None:
    """Requirement 2: Unscheduled Python class on Wednesday cannot generate attendance records."""
    from datetime import date, time
    from app.core.enums import AttendanceStatus
    from app.models.subject import Subject
    from app.models.timetable import TimetableSlot
    from app.adapters.fake.adapter import FakePortalAdapter, SubjectAttendance
    from app.services.confirmation import ConfirmationService
    from app.services.daily_scheduler import DailyCheckRunner

    # Wednesday 2026-09-30 (weekday 2)
    wednesday = date(2026, 9, 30)
    ConfirmationService(db_session).confirm_attendance(wednesday)

    # Create subjects
    ads = Subject(code="301ADS", name="Algorithms")
    pds = Subject(code="303PDS", name="Python for Data Science")
    db_session.add_all([ads, pds])
    db_session.flush()

    # Wednesday timetable only schedules 301ADS, NOT 303PDS
    slot = TimetableSlot(subject_id=ads.id, weekday=2, start_time=time(9), end_time=time(10))
    db_session.add(slot)
    db_session.commit()

    # Adapter tries to return both ADS and unscheduled PDS
    adapter = FakePortalAdapter()
    adapter.set_custom_subjects([
        SubjectAttendance("301ADS", AttendanceStatus.PRESENT, True),
        SubjectAttendance("303PDS", AttendanceStatus.PRESENT, True),
    ])

    runner = DailyCheckRunner(db=db_session)
    result = runner.run_daily_check(target_date=wednesday, adapter=adapter, ignore_cutoff=True)

    assert result.status == "SUCCESS"
    assert result.subjects_checked == 1  # Only 301ADS evaluated
    dec_codes = [d.subject_code for d in result.decisions]
    assert "301ADS" in dec_codes
    assert "303PDS" not in dec_codes


def test_authoritative_attendance_percentage_and_no_pagination_corruption(client: TestClient, db_session) -> None:
    """Requirements 3 & 4: Attendance percentage comes from portal and pagination cannot alter it."""
    from datetime import datetime, timezone
    from app.models.portal_attendance import PortalAttendanceSummary

    # Authoritative summary: 147 / 157 = 94.0%
    summary = PortalAttendanceSummary(
        overall_rate=94.0,
        total_classes=157,
        attended_classes=147,
        missed_classes=10,
        course_count=6,
        sync_status="SYNCED",
        synced_at=datetime.now(timezone.utc),
    )
    db_session.add(summary)
    db_session.commit()

    # Query full summary
    res_full = client.get("/api/history/summary")
    assert res_full.status_code == 200
    acad_full = res_full.json()["academic_attendance"]
    assert acad_full["overall_rate"] == 94.0
    assert acad_full["attended_classes"] == 147
    assert acad_full["total_classes"] == 157

    # Paginate history records with limit=1, offset=0
    res_page = client.get("/api/history?limit=1&offset=0")
    assert res_page.status_code == 200

    # Query summary again: percentage is strictly invariant to pagination
    res_after = client.get("/api/history/summary")
    acad_after = res_after.json()["academic_attendance"]
    assert acad_after["overall_rate"] == 94.0
    assert acad_after["attended_classes"] == 147
    assert acad_after["total_classes"] == 157


def test_calendar_schedule_drives_exact_checkrun_count(client: TestClient, db_session) -> None:
    """Requirements 5, 6, 7, 8, 9, 10: Schedule strictly determines check-run count (5, cancelled=4, extra=6, holiday=0)."""
    from datetime import date, time
    from app.core.enums import AttendanceStatus
    from app.models.calendar import ClassException, ExceptionType, Holiday
    from app.models.subject import Subject
    from app.models.timetable import TimetableSlot
    from app.adapters.fake.adapter import FakePortalAdapter, SubjectAttendance
    from app.services.confirmation import ConfirmationService
    from app.services.daily_scheduler import DailyCheckRunner

    monday = date(2026, 9, 28)  # weekday 0
    ConfirmationService(db_session).confirm_attendance(monday)

    # 1. Setup 5 Monday subjects
    codes = ["301ADS", "302OPS", "303PDS", "304VEP", "306JWD"]
    extra_code = "304ELS"
    subjects = {}
    for code in codes + [extra_code]:
        s = Subject(code=code, name=f"Subject {code}")
        db_session.add(s)
        db_session.flush()
        subjects[code] = s

    # 5 slots on Monday
    for code in codes:
        db_session.add(TimetableSlot(subject_id=subjects[code].id, weekday=0, start_time=time(9), end_time=time(10)))
    db_session.commit()

    adapter = FakePortalAdapter()
    adapter.set_custom_subjects([
        SubjectAttendance(c, AttendanceStatus.PRESENT, True) for c in codes + [extra_code]
    ])

    # Case A: 5 scheduled classes -> 5 evaluated classes
    runner = DailyCheckRunner(db=db_session)
    res_5 = runner.run_daily_check(target_date=monday, adapter=adapter, ignore_cutoff=True)
    assert res_5.status == "SUCCESS"
    assert res_5.subjects_checked == 5
    assert len(res_5.decisions) == 5

    # Case B: 1 cancelled class -> 4 evaluated classes
    db_session.add(ClassException(subject_id=subjects["301ADS"].id, date=monday, exception_type=ExceptionType.CANCELLED))
    db_session.commit()
    res_4 = runner.run_daily_check(target_date=monday, adapter=adapter, ignore_cutoff=True)
    assert res_4.status == "SUCCESS"
    assert res_4.subjects_checked == 4
    assert len(res_4.decisions) == 4

    # Case C: 1 extra class added -> 5 evaluated (4 remaining + 1 extra = 5; or without cancel = 6)
    db_session.add(ClassException(subject_id=subjects[extra_code].id, date=monday, exception_type=ExceptionType.EXTRA))
    db_session.commit()
    res_extra = runner.run_daily_check(target_date=monday, adapter=adapter, ignore_cutoff=True)
    assert res_extra.status == "SUCCESS"
    assert res_extra.subjects_checked == 5  # (5 original - 1 cancelled + 1 extra) = 5
    assert len(res_extra.decisions) == 5

    # Case D: Holiday -> 0 evaluated classes
    holiday_date = date(2026, 10, 2)
    db_session.add(Holiday(date=holiday_date, description="Gandhi Jayanti"))
    db_session.commit()
    res_hol = runner.run_daily_check(target_date=holiday_date, adapter=adapter, ignore_cutoff=True)
    assert res_hol.status == "SUCCESS"
    assert res_hol.reason == "NO_CLASSES_SCHEDULED"
    assert res_hol.subjects_checked == 0
    assert len(res_hol.decisions) == 0


def test_dashboard_and_timetable_consistency(client: TestClient, db_session) -> None:
    """Requirement 11 & 12: Dashboard expected classes and timetable cannot contradict each other."""
    from datetime import date
    from app.models.calendar import Holiday

    today = date.today()
    # If today is set as a holiday
    db_session.add(Holiday(date=today, description="Test Holiday"))
    db_session.commit()

    res = client.get("/api/dashboard/today")
    assert res.status_code == 200
    data = res.json()
    assert data["is_holiday"] is True
    assert len(data["expected_classes"]) == 0
    assert len(data["attendance_records"]) == 0


def test_raw_notes_and_debug_metadata_never_exposed(client: TestClient, db_session) -> None:
    """Requirement 13: Raw internal dictionaries and debug structures never leak to the API."""
    from datetime import date
    from app.core.enums import AttendanceStatus, CheckStatus
    from app.models.attendance_check import AttendanceCheck
    from app.models.attendance_result import AttendanceResult

    chk = AttendanceCheck(
        run_id="audit-test-notes",
        check_date=date(2026, 9, 28),
        adapter_name="audit_test",
        status=CheckStatus.SUCCESS,
    )
    db_session.add(chk)
    db_session.flush()

    raw_dict_string = "{'date': '2026-09-28', 'retries_attempted': 3, 'reason': 'Internal error'}"
    res = AttendanceResult(
        check_id=chk.id,
        subject_code="301ADS",
        status=AttendanceStatus.PRESENT,
        is_reliable=True,
        notes=raw_dict_string,
    )
    db_session.add(res)
    db_session.commit()

    history_res = client.get("/api/history")
    assert history_res.status_code == 200
    for item in history_res.json()["items"]:
        if item["notes"]:
            assert "{" not in item["notes"]
            assert "retries_attempted" not in item["notes"]
            assert "date" not in item["notes"]

