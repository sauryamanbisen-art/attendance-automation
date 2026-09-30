"""Integration tests for Timetable, Calendar, and Dashboard endpoints."""

from datetime import date, time

from fastapi.testclient import TestClient


def test_timetable_api(client: TestClient) -> None:
    """Test timetable slots CRUD."""
    # Ensure subject exists
    subj_payload = {
        "code": "TS101",
        "name": "Test Subject 101",
    }
    subj_res = client.post("/api/subjects", json=subj_payload)
    assert subj_res.status_code in [201, 409]
    # Get the ID
    if subj_res.status_code == 201:
        subj_id = subj_res.json()["id"]
    else:
        # Fetch it
        subs = client.get("/api/subjects").json()
        subj_id = next(s["id"] for s in subs if s["code"] == "TS101")

    # 1. Create Timetable Slot
    slot_payload = {
        "subject_id": subj_id,
        "weekday": 0,
        "start_time": "09:00:00",
        "end_time": "10:00:00",
    }
    create_res = client.post("/api/timetable/", json=slot_payload)
    assert create_res.status_code == 201
    slot = create_res.json()
    assert slot["subject_id"] == subj_id
    slot_id = slot["id"]

    # 2. List slots
    list_res = client.get("/api/timetable/")
    assert list_res.status_code == 200
    assert any(s["id"] == slot_id for s in list_res.json())

    # 3. Validation failure
    invalid_payload = {
        "subject_id": subj_id,
        "weekday": 0,
        "start_time": "09:00:00",
        "end_time": "10:00:00",
        "valid_from": "2026-02-01",
        "valid_to": "2026-01-01"  # Invalid, valid_from > valid_to
    }
    res_inv = client.post("/api/timetable/", json=invalid_payload)
    assert res_inv.status_code == 400

    # 4. Update slot (PUT)
    update_payload = {
        "subject_id": subj_id,
        "weekday": 1,
        "start_time": "10:00:00",
        "end_time": "11:00:00",
    }
    update_res = client.put(f"/api/timetable/{slot_id}", json=update_payload)
    assert update_res.status_code == 200
    updated_slot = update_res.json()
    assert updated_slot["weekday"] == 1
    assert updated_slot["start_time"] == "10:00:00"

    # 5. Delete slot
    del_res = client.delete(f"/api/timetable/{slot_id}")
    assert del_res.status_code == 204


def test_calendar_api(client: TestClient) -> None:
    """Test holidays and exceptions CRUD."""
    # 1. Create Holiday
    h_payload = {
        "date": "2026-10-31",
        "description": "Halloween"
    }
    h_create = client.post("/api/calendar/holidays", json=h_payload)
    assert h_create.status_code == 201
    h_id = h_create.json()["id"]

    # 2. Duplicate holiday -> 400
    h_dup = client.post("/api/calendar/holidays", json=h_payload)
    assert h_dup.status_code == 400

    # 3. List holidays
    h_list = client.get("/api/calendar/holidays")
    assert any(h["id"] == h_id for h in h_list.json())

    # 4. Delete holiday
    client.delete(f"/api/calendar/holidays/{h_id}")

    # --- Exceptions ---
    # Fetch or create subject
    subj_payload = {"code": "TS202", "name": "Test Subject 202"}
    client.post("/api/subjects", json=subj_payload)
    subs = client.get("/api/subjects").json()
    subj_id = next(s["id"] for s in subs if s["code"] == "TS202")

    e_payload = {
        "subject_id": subj_id,
        "date": "2026-11-01",
        "exception_type": "CANCELLED"
    }
    e_create = client.post("/api/calendar/exceptions", json=e_payload)
    assert e_create.status_code == 201
    e_id = e_create.json()["id"]

    # Duplicate exception of same type -> 400
    e_dup = client.post("/api/calendar/exceptions", json=e_payload)
    assert e_dup.status_code == 400
    assert "already exists" in e_dup.json()["detail"]

    # Conflicting exception of opposite type -> 400
    e_conflict = client.post("/api/calendar/exceptions", json={
        "subject_id": subj_id,
        "date": "2026-11-01",
        "exception_type": "EXTRA",
        "start_time": "09:00:00",
        "end_time": "10:00:00",
    })
    assert e_conflict.status_code == 400
    assert "conflicting" in e_conflict.json()["detail"]

    # Invalid time range (start >= end) -> 400
    e_bad_time = client.post("/api/calendar/exceptions", json={
        "subject_id": subj_id,
        "date": "2026-11-02",
        "exception_type": "EXTRA",
        "start_time": "11:00:00",
        "end_time": "10:00:00",
    })
    assert e_bad_time.status_code == 400
    assert "start_time must be before end_time" in e_bad_time.json()["detail"]

    e_list = client.get("/api/calendar/exceptions")
    assert any(e["id"] == e_id for e in e_list.json())

    client.delete(f"/api/calendar/exceptions/{e_id}")


def test_timetable_time_validation(client: TestClient) -> None:
    """Test start_time >= end_time validation for timetable slots."""
    subj_res = client.post("/api/subjects", json={"code": "TIME101", "name": "Time Test"})
    assert subj_res.status_code == 201
    subj_id = subj_res.json()["id"]

    # start_time == end_time -> 400
    res_eq = client.post("/api/timetable/", json={
        "subject_id": subj_id,
        "weekday": 0,
        "start_time": "10:00:00",
        "end_time": "10:00:00",
    })
    assert res_eq.status_code == 400
    assert "start_time must be before end_time" in res_eq.json()["detail"]

    # start_time > end_time -> 400
    res_gt = client.post("/api/timetable/", json={
        "subject_id": subj_id,
        "weekday": 0,
        "start_time": "11:00:00",
        "end_time": "10:00:00",
    })
    assert res_gt.status_code == 400
    assert "start_time must be before end_time" in res_gt.json()["detail"]


def test_subject_cascades_delete_timetable_and_exceptions(client: TestClient) -> None:
    """Deleting a subject must cleanly cascade-delete associated slots and exceptions."""
    # 1. Create unique subject
    subj_res = client.post("/api/subjects", json={"code": "CASCADE101", "name": "Cascade Test"})
    assert subj_res.status_code == 201
    subj_id = subj_res.json()["id"]

    # 2. Add slot and exception
    slot_res = client.post("/api/timetable/", json={
        "subject_id": subj_id,
        "weekday": 2,
        "start_time": "09:00:00",
        "end_time": "10:00:00",
    })
    assert slot_res.status_code == 201
    slot_id = slot_res.json()["id"]

    exc_res = client.post("/api/calendar/exceptions", json={
        "subject_id": subj_id,
        "date": "2026-12-25",
        "exception_type": "CANCELLED",
    })
    assert exc_res.status_code == 201
    exc_id = exc_res.json()["id"]

    # 3. Delete subject
    del_sub = client.delete("/api/subjects/CASCADE101")
    assert del_sub.status_code == 204

    # 4. Verify slot and exception are gone
    slots = client.get("/api/timetable/").json()
    assert not any(s["id"] == slot_id for s in slots)

    exceptions = client.get("/api/calendar/exceptions").json()
    assert not any(e["id"] == exc_id for e in exceptions)


def test_dashboard_api(client: TestClient) -> None:
    """Test dashboard aggregation."""
    res = client.get("/api/dashboard/today")
    assert res.status_code == 200
    data = res.json()
    assert "today" in data
    assert "is_holiday" in data
    assert "is_confirmed" in data
    assert "expected_classes" in data
    assert "attendance_records" in data
