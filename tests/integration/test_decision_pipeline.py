"""End-to-end integration test of the confirmation and decision pipeline."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.notification_event import NotificationEvent
from app.models.subject import Subject


def test_complete_decision_lifecycle(client: TestClient, db_session: Session) -> None:
    """Test the full lifecycle from unconfirmed to confirmed, eligible, and deduplicated."""
    test_date = "2026-09-25"

    # Step 1: Register subject with professor mapping
    sub_res = client.post(
        "/api/subjects",
        json={
            "code": "303PDS",
            "name": "Python for Data Science",
            "professor_name": "Dr. Alan Turing",
            "professor_email": "turing@university.edu",
        },
    )
    assert sub_res.status_code == 201

    # Step 2: Run check without student confirmation (scenario=python_absent)
    check1 = client.post(
        "/api/checks/run",
        json={"date": test_date, "scenario": "python_absent"},
    )
    assert check1.status_code == 200
    d1 = check1.json()["decisions"][0]
    assert d1["action"] == "NO_ACTION"
    assert d1["reason"] == "ATTENDANCE_NOT_CONFIRMED"

    # Step 3: Student confirms daily attendance ('I WENT TO COLLEGE')
    conf_res = client.post(
        "/api/confirmations",
        json={"date": test_date, "note": "Present for full day"},
    )
    assert conf_res.status_code == 200
    assert conf_res.json()["created"] is True

    # Step 4: Run check again after confirmation
    check2 = client.post(
        "/api/checks/run",
        json={"date": test_date, "scenario": "python_absent"},
    )
    assert check2.status_code == 200
    d2 = check2.json()["decisions"][0]
    # Now eligible!
    assert d2["action"] == "ELIGIBLE_FOR_NOTIFICATION"
    assert d2["reason"] == "ABSENT_AND_CONFIRMED"
    assert d2["professor_email"] == "turing@university.edu"

    # Step 5: Simulate recording notification in the database
    subject = db_session.query(Subject).filter(Subject.code == "303PDS").first()
    assert subject is not None
    db_session.add(
        NotificationEvent(
            date=date(2026, 9, 25),
            subject_id=subject.id,
            subject_code=subject.code,
            recipient_email="turing@university.edu",
        )
    )
    db_session.commit()

    # Step 6: Subsequent run on same date must be deduplicated
    check3 = client.post(
        "/api/checks/run",
        json={"date": test_date, "scenario": "python_absent"},
    )
    assert check3.status_code == 200
    d3 = check3.json()["decisions"][0]
    assert d3["action"] == "NO_ACTION"
    assert d3["reason"] == "ALREADY_NOTIFIED"

    # Step 7: Checking a different date (e.g. tomorrow) must NOT inherit confirmation
    check4 = client.post(
        "/api/checks/run",
        json={"date": "2026-09-26", "scenario": "python_absent"},
    )
    assert check4.status_code == 200
    d4 = check4.json()["decisions"][0]
    assert d4["action"] == "NO_ACTION"
    assert d4["reason"] == "ATTENDANCE_NOT_CONFIRMED"


def test_unreliable_absent_fails_closed_in_production_pipeline(
    client: TestClient, db_session: Session
) -> None:
    """CRITICAL SAFETY TEST: Even with confirmed attendance and valid professor mapping,
    an unreliable ABSENT result from the adapter MUST NEVER become ELIGIBLE_FOR_NOTIFICATION.

    Verifies propagation through:
    Fake/Portal Adapter -> AttendanceCheck -> AttendanceResult -> DecisionEngine -> DecisionResult -> API Response -> Audit Log
    """
    from app.models.attendance_result import AttendanceResult

    test_date = "2026-09-27"

    # 1. Register subject with professor mapping
    client.post(
        "/api/subjects",
        json={
            "code": "303PDS",
            "name": "Python for Data Science",
            "professor_name": "Dr. Alan Turing",
            "professor_email": "turing@university.edu",
        },
    )

    # 2. Student confirms attendance for test_date ('I WENT TO COLLEGE')
    conf_res = client.post(
        "/api/confirmations",
        json={"date": test_date, "note": "Present all day"},
    )
    assert conf_res.status_code == 200
    assert conf_res.json()["created"] is True

    # 3. Trigger check run with unreliable_absent scenario
    check_res = client.post(
        "/api/checks/run",
        json={"date": test_date, "scenario": "unreliable_absent"},
    )
    assert check_res.status_code == 200
    data = check_res.json()

    # Check status and run_id
    assert data["status"] == "SUCCESS"
    run_id = data["run_id"]

    # Verify results payload
    assert len(data["results"]) == 1
    subject_result = data["results"][0]
    assert subject_result["subject_code"] == "303PDS"
    assert subject_result["status"] == "ABSENT"
    assert subject_result["is_reliable"] is False

    # Verify decision payload: MUST FAIL CLOSED (NO_ACTION)
    assert len(data["decisions"]) == 1
    decision = data["decisions"][0]
    assert decision["action"] == "NO_ACTION"
    assert decision["reason"] == "UNRELIABLE_ATTENDANCE_RESULT"
    assert decision["is_reliable"] is False
    assert decision["is_confirmed"] is True
    assert decision["status"] == "ABSENT"

    # 4. Verify AttendanceResult persisted in DB has is_reliable=False
    db_result = (
        db_session.query(AttendanceResult)
        .filter(AttendanceResult.subject_code == "303PDS")
        .order_by(AttendanceResult.id.desc())
        .first()
    )
    assert db_result is not None
    assert db_result.is_reliable is False
    assert db_result.status.value == "ABSENT"

    # 5. Verify audit log captures is_reliable=False and UNRELIABLE_ATTENDANCE_RESULT
    audit_res = client.get(f"/api/audit?run_id={run_id}")
    assert audit_res.status_code == 200
    audit_events = audit_res.json()
    assert len(audit_events) >= 1
    check_event = audit_events[0]
    assert check_event["action"] == "RUN_ATTENDANCE_CHECK"
    decision_logged = check_event["details"]["decisions"][0]
    assert decision_logged["action"] == "NO_ACTION"
    assert decision_logged["reason"] == "UNRELIABLE_ATTENDANCE_RESULT"
    assert decision_logged["is_reliable"] is False


def test_malformed_and_ambiguous_scenarios_fail_closed_in_pipeline(
    client: TestClient,
) -> None:
    """Test that malformed, ambiguous, and unavailable scenarios fail closed through API pipeline."""
    test_date = "2026-09-28"

    # Confirm attendance
    client.post("/api/confirmations", json={"date": test_date})

    # Scenario: malformed_response
    res_malformed = client.post(
        "/api/checks/run",
        json={"date": test_date, "scenario": "malformed_response"},
    )
    assert res_malformed.status_code == 200
    d_malformed = res_malformed.json()["decisions"][0]
    assert d_malformed["action"] == "NO_ACTION"
    assert d_malformed["status"] == "UNKNOWN"
    assert d_malformed["is_reliable"] is False

    # Scenario: ambiguous_response
    res_ambiguous = client.post(
        "/api/checks/run",
        json={"date": test_date, "scenario": "ambiguous_response"},
    )
    assert res_ambiguous.status_code == 200
    d_ambiguous = res_ambiguous.json()["decisions"][0]
    assert d_ambiguous["action"] == "NO_ACTION"
    assert d_ambiguous["status"] == "UNKNOWN"
    assert d_ambiguous["is_reliable"] is False

    # Scenario: portal_unavailable
    res_unavail = client.post(
        "/api/checks/run",
        json={"date": test_date, "scenario": "portal_unavailable"},
    )
    assert res_unavail.status_code == 200
    assert res_unavail.json()["status"] == "FAILED"
    assert len(res_unavail.json()["decisions"]) == 0

