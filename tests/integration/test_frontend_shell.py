"""Integration tests for the frontend application shell."""

from fastapi.testclient import TestClient

def test_dashboard_html_served(client: TestClient) -> None:
    """Verify the frontend application shell is served on /dashboard."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text
    
    # Check for core shell elements
    assert "<title>Attendance Automation Dashboard</title>" in html
    assert 'class="app-shell"' in html
    assert 'id="app-sidebar"' in html
    assert 'id="main-content"' in html
    
    # Check for correct JS module inclusion
    assert 'type="module" src="/static/js/main.js"' in html


def test_static_assets_served(client: TestClient) -> None:
    """Verify static JS and CSS files are properly mounted and served."""
    # Test CSS
    res_css = client.get("/static/css/shell.css")
    assert res_css.status_code == 200
    assert ".app-shell" in res_css.text

    # Test JS Main Module
    res_js_main = client.get("/static/js/main.js")
    assert res_js_main.status_code == 200
    assert "export" in res_js_main.text or "import" in res_js_main.text
    
    # Test JS API Module
    res_js_api = client.get("/static/js/api.js")
    assert res_js_api.status_code == 200
    assert "class ApiError" in res_js_api.text
