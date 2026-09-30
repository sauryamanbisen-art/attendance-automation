"""Integration tests for the frontend history shell."""

from fastapi.testclient import TestClient

def test_history_html_served(client: TestClient) -> None:
    """Verify the attendance history frontend shell is present."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    
    # Check for Attendance History page container
    assert 'id="page-attendance"' in html
    
    # Check for core history elements
    assert 'id="filter-history-subject"' in html
    assert 'id="filter-history-start"' in html
    assert 'id="filter-history-end"' in html
    assert 'id="btn-apply-history-filters"' in html
    assert 'id="history-table-body"' in html
    assert 'id="history-pagination-info"' in html

def test_static_history_js_served(client: TestClient) -> None:
    """Verify static JS history files are properly mounted and served."""
    res_js = client.get("/static/js/pages/history.js")
    assert res_js.status_code == 200
    assert "export class HistoryController" in res_js.text
    
    # Validate API usage exists
    assert "API.history.list" in res_js.text
