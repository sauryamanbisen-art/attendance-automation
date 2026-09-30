"""Integration tests for the frontend settings shell and notification providers."""

from fastapi.testclient import TestClient


def test_settings_html_served(client: TestClient) -> None:
    """Verify the settings frontend shell is present."""
    res = client.get("/dashboard")
    assert res.status_code == 200
    html = res.text

    # Check for Settings page container
    assert 'id="page-settings"' in html

    # Check for core settings elements
    assert 'id="session-status-badge"' in html
    assert 'id="btn-clear-session"' in html
    assert 'id="setting-timezone"' in html
    assert 'id="setting-dry-run"' in html
    assert 'id="setting-portal-adapter"' in html
    assert 'id="notification-providers-list"' in html

    # Check for security notice
    assert "Security & Immutability Architecture" in html

    # Check no secrets are leaked in HTML
    assert "client_secret" not in html
    assert "ya29." not in html


def test_static_settings_js_served(client: TestClient) -> None:
    """Verify static JS settings files are properly mounted and served."""
    res_js = client.get("/static/js/pages/settings.js")
    assert res_js.status_code == 200
    assert "export class SettingsController" in res_js.text

    # Validate API usage exists
    assert "API.settings.read" in res_js.text
    assert "API.settings.getSessionStatus" in res_js.text
    assert "API.settings.clearSession" in res_js.text
    assert "API.notifications.getProviders" in res_js.text
    assert "API.notifications.disconnectProvider" in res_js.text

    # Validate provider rendering and disconnect handling
    assert "renderProviders" in res_js.text
    assert "disconnectProvider" in res_js.text
    assert "checkOAuthCallbackAlerts" in res_js.text
    assert "Provider disconnected locally" in res_js.text
    assert "escapeHtml" in res_js.text

    # Validate no secrets in JS code
    assert "client_secret" not in res_js.text
    assert "ya29." not in res_js.text
