"""Integration tests for the enhanced frontend dashboard."""

from datetime import date
from fastapi.testclient import TestClient


def test_dashboard_enhanced_elements_served(client: TestClient) -> None:
    """Verify that the enhanced dashboard elements and modal exist in /dashboard."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text

    # Core Stats Grid
    assert 'id="stat-check-status"' in html
    assert 'id="stat-confirmation-status"' in html
    assert 'id="stat-subject-breakdown"' in html
    assert 'id="stat-session-status"' in html

    # Action Button & Modal
    assert 'id="btn-open-run-check"' in html
    assert 'id="modal-run-check"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'id="run-check-session-warning"' in html
    assert 'id="btn-execute-run-check"' in html
    assert 'id="input-run-check-date"' in html

    # Recent Checks, Notifications, and Navigation Links
    assert 'id="dashboard-recent-checks"' in html
    assert 'id="dashboard-notifications-feed"' in html
    assert 'id="btn-quick-manage-subjects"' in html
    assert 'id="tab-subjects"' in html


def test_dashboard_js_api_integration(client: TestClient) -> None:
    """Verify dashboard.js and api.js contain new checks and health endpoints."""
    res_api = client.get("/static/js/api.js")
    assert res_api.status_code == 200
    assert "checks:" in res_api.text
    assert "health:" in res_api.text

    res_dash = client.get("/static/js/pages/dashboard.js")
    assert res_dash.status_code == 200
    assert "API.checks.getLatest" in res_dash.text
    assert "API.checks.run" in res_dash.text
    assert "API.checks.getNotifications" in res_dash.text
    assert "btnQuickManageSubjects" in res_dash.text
    assert "openRunCheckModal" in res_dash.text
    assert "executeManualCheck" in res_dash.text


def test_dashboard_backend_api_integration(client: TestClient) -> None:
    """Verify backend API endpoints consumed by dashboard work end-to-end."""
    # 1. Today dashboard state
    res_today = client.get("/api/dashboard/today")
    assert res_today.status_code == 200
    today_data = res_today.json()
    assert "today" in today_data
    assert "is_confirmed" in today_data
    assert "is_holiday" in today_data
    assert "expected_classes" in today_data
    assert "attendance_records" in today_data

    # 2. Latest check
    res_latest = client.get("/api/checks/latest")
    assert res_latest.status_code == 200
    assert "check" in res_latest.json()

    # 3. Recent notifications
    res_notifs = client.get("/api/checks/notifications?limit=5")
    assert res_notifs.status_code == 200
    assert isinstance(res_notifs.json(), list)

    # 4. Session status
    res_session = client.get("/api/settings/session")
    assert res_session.status_code == 200
    assert "is_authenticated" in res_session.json()

    # 5. Run manual check safely via fake scenario
    target_date = date.today().isoformat()
    res_run = client.post("/api/checks/run", json={"date": target_date, "scenario": "present"})
    assert res_run.status_code == 200
    run_data = res_run.json()
    assert run_data["status"] == "SUCCESS"
    assert len(run_data["results"]) > 0
    assert len(run_data["decisions"]) > 0

    # 6. Verify latest check reflects the run
    res_latest_after = client.get("/api/checks/latest")
    assert res_latest_after.status_code == 200
    check_info = res_latest_after.json()["check"]
    assert check_info is not None
    assert check_info["status"] == "SUCCESS"
    assert check_info["run_id"] == run_data["run_id"]

    # 7. Confirm attendance and verify today dashboard updates
    res_confirm = client.post("/api/confirmations", json={"date": target_date, "note": "Integration Test Confirmation"})
    assert res_confirm.status_code == 200

    res_today_confirmed = client.get("/api/dashboard/today")
    assert res_today_confirmed.status_code == 200
    assert res_today_confirmed.json()["is_confirmed"] is True
