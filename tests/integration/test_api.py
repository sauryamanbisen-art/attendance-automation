"""Integration tests for FastAPI endpoints."""

from datetime import date

from fastapi.testclient import TestClient


def test_health_and_root(client: TestClient) -> None:
    """Verify health and root endpoints."""
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "online"

    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"
    assert res_health.json()["adapter"] == "pwioi"


def test_confirmations_api_flow(client: TestClient) -> None:
    """Test attendance confirmation creation and retrieval via API."""
    target_date = "2026-09-25"

    # Step 1: Not confirmed yet
    res_get = client.get(f"/api/confirmations/{target_date}")
    assert res_get.status_code == 404

    # Step 2: Confirm attendance
    payload = {"date": target_date, "note": "Attended all classes today"}
    res_post1 = client.post("/api/confirmations", json=payload)
    assert res_post1.status_code == 200
    data1 = res_post1.json()
    assert data1["date"] == target_date
    assert data1["created"] is True
    assert data1["note"] == "Attended all classes today"

    # Step 3: Confirm again (idempotent)
    res_post2 = client.post("/api/confirmations", json=payload)
    assert res_post2.status_code == 200
    data2 = res_post2.json()
    assert data2["created"] is False
    assert data2["id"] == data1["id"]

    # Step 4: Retrieve confirmed date
    res_get_after = client.get(f"/api/confirmations/{target_date}")
    assert res_get_after.status_code == 200
    assert res_get_after.json()["date"] == target_date


def test_subjects_and_mappings_api(client: TestClient) -> None:
    """Test subject registration and professor mapping via API."""
    # 1. Create subject
    payload = {
        "code": "303PDS",
        "name": "Python Programming",
        "professor_name": "Dr. Alan Turing",
        "professor_email": "turing@university.edu",
    }
    res = client.post("/api/subjects", json=payload)
    assert res.status_code == 201
    assert res.json()["code"] == "303PDS"
    assert res.json()["professor_email"] == "turing@university.edu"

    # 2. Duplicate code -> 409 Conflict
    res_dup = client.post("/api/subjects", json=payload)
    assert res_dup.status_code == 409

    # 3. List subjects
    res_list = client.get("/api/subjects")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # 4. Update professor mapping via mapping endpoint (legacy, but keep it)
    map_payload = {
        "professor_name": "Prof. Ada Lovelace",
        "professor_email": "ada@university.edu",
    }
    res_map = client.post("/api/subjects/303PDS/mapping", json=map_payload)
    assert res_map.status_code == 200
    assert res_map.json()["professor_name"] == "Prof. Ada Lovelace"
    assert res_map.json()["professor_email"] == "ada@university.edu"

    # 5. Update subject via PUT endpoint
    update_payload = {
        "code": "303PDSX",
        "name": "Advanced Python",
        "professor_name": "Prof. Turing",
        "professor_email": "alan@university.edu",
        "google_chat_space": "spaces/TEST"
    }
    res_put = client.put("/api/subjects/303PDS", json=update_payload)
    assert res_put.status_code == 200
    assert res_put.json()["code"] == "303PDSX"
    assert res_put.json()["name"] == "Advanced Python"
    assert res_put.json()["professor_email"] == "alan@university.edu"
    assert res_put.json()["google_chat_space"] == "spaces/TEST"

    # 6. Delete subject via DELETE endpoint
    res_del = client.delete("/api/subjects/303PDSX")
    assert res_del.status_code == 204
    
    # 7. Check if deleted
    res_list2 = client.get("/api/subjects")
    assert not any(s["code"] == "303PDSX" for s in res_list2.json())


def test_checks_and_audit_api(client: TestClient) -> None:
    """Test running checks with fake adapter scenarios and inspecting audit logs."""
    # Run check with python_present scenario
    check_payload = {
        "date": "2026-09-25",
        "scenario": "python_present",
    }
    res = client.post("/api/checks/run", json=check_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert len(data["results"]) == 1
    assert data["results"][0]["status"] == "PRESENT"
    assert data["decisions"][0]["action"] == "NO_ACTION"

    # Run check with unavailable portal scenario
    res_err = client.post("/api/checks/run", json={"scenario": "portal_unavailable"})
    assert res_err.status_code == 200
    assert res_err.json()["status"] == "FAILED"

    # Query audit logs
    audit_res = client.get("/api/audit")
    assert audit_res.status_code == 200
    events = audit_res.json()
    assert len(events) >= 1


def test_settings_api_safety(client: TestClient) -> None:
    """Verify settings endpoint only returns safe metadata."""
    res = client.get("/api/settings")
    assert res.status_code == 200
    settings = res.json()
    
    # Must explicitly contain safe configuration
    assert "timezone" in settings
    assert "portal_adapter" in settings
    
    # Must NEVER contain sensitive fields
    assert "portal_password" not in settings
    assert "google_chat_client_secret" not in settings
    assert "gmail_client_secret" not in settings
    assert "google_chat_token_file" not in settings

def test_settings_session_api(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Verify session management API safely reports status and handles deletion without touching real files."""
    test_session_file = tmp_path / "mock_session.json"
    test_session_file.write_text("{}", encoding="utf-8")

    from app.config import get_settings
    current_settings = get_settings()
    monkeypatch.setattr(current_settings, "pwioi_storage_state", str(test_session_file))
    monkeypatch.setattr(current_settings, "portal_storage_state", str(test_session_file))

    res = client.get("/api/settings/session")
    assert res.status_code == 200
    data = res.json()
    assert data["is_authenticated"] is True
    assert data["session_file_exists"] is True

    # Test safe deletion
    res_del = client.delete("/api/settings/session")
    assert res_del.status_code == 204
    assert not test_session_file.exists()

    # Status after deletion
    res_after = client.get("/api/settings/session")
    assert res_after.status_code == 200
    data_after = res_after.json()
    assert data_after["is_authenticated"] is False
    assert data_after["session_file_exists"] is False

def test_notifications_providers_api(client: TestClient) -> None:
    """Verify notification providers endpoint safely reports connection status."""
    res = client.get("/api/notifications/providers")
    assert res.status_code == 200
    data = res.json()
    
    assert "providers" in data
    assert len(data["providers"]) == 2
    
    gc_provider = next(p for p in data["providers"] if p["id"] == "google_chat")
    assert "connected" in gc_provider
    assert "is_configured" in gc_provider
    assert "client_secret" not in gc_provider
    
    # Test secure disconnect API
    res_del = client.delete("/api/notifications/google_chat/authorization")
    assert res_del.status_code == 204
    
    res_invalid = client.delete("/api/notifications/invalid_provider/authorization")
    assert res_invalid.status_code == 404


def test_history_api(client: TestClient) -> None:
    """Test history API endpoint filters and pagination."""
    # Run a check to generate history
    client.post("/api/checks/run", json={"date": "2026-09-26", "scenario": "python_present"})
    
    # Get history without filters
    res = client.get("/api/history")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    
    # Filter by date
    res_date = client.get("/api/history?start_date=2026-09-26&end_date=2026-09-26")
    assert res_date.status_code == 200
    assert len(res_date.json()["items"]) >= 1
    
    # Filter by subject
    res_subj = client.get("/api/history?subject_code=303PDS")
    assert res_subj.status_code == 200
    assert len(res_subj.json()["items"]) >= 1
    
    # Pagination
    res_page = client.get("/api/history?limit=1&offset=0")
    assert res_page.status_code == 200
    assert len(res_page.json()["items"]) <= 1

