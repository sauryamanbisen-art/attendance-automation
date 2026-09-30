"""Integration tests for Google Chat OAuth endpoints and space management."""

import json
import socket
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from app.notifications.google_chat.oauth import InMemoryTokenStorage, OAuthToken
from app.services.google_chat_oauth_service import (
    GoogleChatOAuthService,
    OAuthStateManager,
    get_oauth_state_manager,
)
from main import app


@pytest.fixture(name="test_state_manager")
def fixture_test_state_manager() -> OAuthStateManager:
    """Fresh in-memory state manager for each test."""
    manager = OAuthStateManager(ttl_seconds=600)
    return manager


@pytest.fixture(name="configured_settings")
def fixture_configured_settings() -> Settings:
    """Settings configured with mock Google Chat OAuth credentials."""
    return Settings(
        google_chat_client_id="test_client_id_123.apps.googleusercontent.com",
        google_chat_client_secret="test_super_secret_client_key_456",
        google_chat_redirect_uri="http://localhost:8000/api/auth/google-chat/callback",
        google_chat_default_space="spaces/DEFAULT_FALLBACK",
        dry_run=True,
    )


@pytest.fixture(name="unconfigured_settings")
def fixture_unconfigured_settings() -> Settings:
    """Settings with no Google Chat OAuth credentials and isolated token path."""
    return Settings(
        google_chat_client_id=None,
        google_chat_client_secret=None,
        google_chat_token_file="nonexistent_test_credentials.json",
        dry_run=True,
    )


@pytest.fixture(name="memory_token_storage")
def fixture_memory_token_storage() -> InMemoryTokenStorage:
    """In-memory token storage for tests."""
    return InMemoryTokenStorage()


@pytest.fixture(name="oauth_test_client")
def fixture_oauth_test_client(
    db_session: Session,
    configured_settings: Settings,
    memory_token_storage: InMemoryTokenStorage,
    test_state_manager: OAuthStateManager,
) -> TestClient:
    """TestClient wired with in-memory DB, configured settings, memory token storage, and state manager."""
    service = GoogleChatOAuthService(
        settings=configured_settings,
        token_storage=memory_token_storage,
        state_manager=test_state_manager,
    )

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: configured_settings
    app.dependency_overrides[get_oauth_state_manager] = lambda: test_state_manager
    from app.api.google_chat import get_google_chat_service

    app.dependency_overrides[get_google_chat_service] = lambda: service

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(name="guard_network", autouse=True)
def fixture_guard_network():
    """Verify that tests NEVER make real outbound network connections."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        raise AssertionError(f"Outbound network connection attempted to {address} during test execution!")

    with patch.object(socket.socket, "connect", guarded_connect):
        yield


# ═══════════════════════════════════════════════════════════════════════════
# 1. OAuth Unconfigured Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_authorize_unconfigured_fails(
    db_session: Session,
    unconfigured_settings: Settings,
    memory_token_storage: InMemoryTokenStorage,
    guard_network,
):
    """When OAuth client credentials are not configured, /authorize returns 400 Bad Request."""
    service = GoogleChatOAuthService(
        settings=unconfigured_settings,
        token_storage=memory_token_storage,
    )
    from app.api.google_chat import get_google_chat_service

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: unconfigured_settings
    app.dependency_overrides[get_google_chat_service] = lambda: service

    with TestClient(app) as client:
        res = client.get("/api/auth/google-chat/authorize")
        assert res.status_code == 400
        assert "Google Chat OAuth is not configured" in res.json()["detail"]

        # Status endpoint reports configured=False
        status_res = client.get("/api/auth/google-chat/status")
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["configured"] is False
        assert data["connected"] is False

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Authorize Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_authorize_json_response(oauth_test_client: TestClient, guard_network):
    """Verify /authorize generates a valid Google authorization URL and tracks CSRF state."""
    res = oauth_test_client.get("/api/auth/google-chat/authorize")
    assert res.status_code == 200
    data = res.json()
    assert "authorization_url" in data
    assert "state" in data
    auth_url = data["authorization_url"]
    state = data["state"]

    assert "https://accounts.google.com/o/oauth2/v2/auth" in auth_url
    assert "client_id=test_client_id_123.apps.googleusercontent.com" in auth_url
    assert f"state={state}" in auth_url
    assert "access_type=offline" in auth_url
    assert "prompt=consent" in auth_url


def test_authorize_redirect_response(oauth_test_client: TestClient, guard_network):
    """Verify /authorize with redirect=true returns a 307 Temporary Redirect."""
    res = oauth_test_client.get("/api/auth/google-chat/authorize?redirect=true", follow_redirects=False)
    assert res.status_code == 307
    location = res.headers.get("location", "")
    assert "https://accounts.google.com/o/oauth2/v2/auth" in location
    assert "client_id=test_client_id_123.apps.googleusercontent.com" in location


# ═══════════════════════════════════════════════════════════════════════════
# 3. Callback State Validation & User Denial Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_callback_missing_or_invalid_state(oauth_test_client: TestClient, guard_network):
    """Callback rejects missing or unknown CSRF state tokens."""
    # 1. Missing state
    res1 = oauth_test_client.get("/api/auth/google-chat/callback?code=mock_code")
    assert res1.status_code == 400
    assert "state parameter" in res1.json()["detail"].lower()

    # 2. Unknown state
    res2 = oauth_test_client.get("/api/auth/google-chat/callback?code=mock_code&state=forged_state_token")
    assert res2.status_code == 400
    assert "invalid or expired" in res2.json()["detail"].lower()


def test_callback_consumed_state_cannot_be_reused(oauth_test_client: TestClient, guard_network):
    """CSRF state tokens are single-use; reusing a state token must fail."""
    # Generate state
    auth_res = oauth_test_client.get("/api/auth/google-chat/authorize")
    state = auth_res.json()["state"]

    # Mock HTTP response for token exchange
    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "mock_access_tok_1",
            "refresh_token": "mock_refresh_tok_1",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/chat.messages.create",
        }
        mock_post.return_value = mock_resp

        # First use succeeds
        res1 = oauth_test_client.get(f"/api/auth/google-chat/callback?code=code_1&state={state}")
        assert res1.status_code == 200
        assert res1.json()["status"] == "connected"

        # Replay attempt fails
        res2 = oauth_test_client.get(f"/api/auth/google-chat/callback?code=code_2&state={state}")
        assert res2.status_code == 400
        assert "invalid or expired" in res2.json()["detail"].lower()


def test_callback_denied_authorization(oauth_test_client: TestClient, guard_network):
    """Handle user cancellation or access denied safely without throwing unhandled errors."""
    res = oauth_test_client.get(
        "/api/auth/google-chat/callback?error=access_denied&error_description=User+declined+permission"
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "denied or cancelled" in detail.lower()
    assert "declined permission" in detail.lower()


def test_callback_missing_code(oauth_test_client: TestClient, guard_network):
    """Callback with valid state but missing authorization code fails cleanly."""
    auth_res = oauth_test_client.get("/api/auth/google-chat/authorize")
    state = auth_res.json()["state"]

    res = oauth_test_client.get(f"/api/auth/google-chat/callback?state={state}")
    assert res.status_code == 400
    assert "code is missing" in res.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# 4. Token Exchange Success & Failure Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_callback_token_exchange_success(
    oauth_test_client: TestClient,
    memory_token_storage: InMemoryTokenStorage,
    guard_network,
):
    """Successful OAuth callback exchanges code, stores tokens, and redacts secrets from response."""
    auth_res = oauth_test_client.get("/api/auth/google-chat/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ya29.sensitive_access_token_xyz",
            "refresh_token": "1//sensitive_refresh_token_abc",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/chat.messages.create",
            "token_type": "Bearer",
        }
        mock_post.return_value = mock_resp

        res = oauth_test_client.get(f"/api/auth/google-chat/callback?code=mock_auth_code_123&state={state}")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "connected"
        assert "Credentials stored securely" in data["message"]

        # CRITICAL: Verify secrets are NEVER exposed in the callback response
        res_str = json.dumps(data)
        assert "ya29.sensitive_access_token_xyz" not in res_str
        assert "1//sensitive_refresh_token_abc" not in res_str
        assert "mock_auth_code_123" not in res_str
        assert "test_super_secret_client_key_456" not in res_str

        # Verify token is safely stored
        stored = memory_token_storage.load_token()
        assert stored is not None
        assert stored.access_token == "ya29.sensitive_access_token_xyz"
        assert stored.refresh_token == "1//sensitive_refresh_token_abc"


def test_callback_token_exchange_server_error(oauth_test_client: TestClient, guard_network):
    """Handle token endpoint error (e.g. invalid_grant or bad code) gracefully."""
    auth_res = oauth_test_client.get("/api/auth/google-chat/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Code was expired or already redeemed",
        }
        mock_post.return_value = mock_resp

        res = oauth_test_client.get(f"/api/auth/google-chat/callback?code=bad_code&state={state}")
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "Code was expired or already redeemed" in detail


def test_callback_network_timeout(oauth_test_client: TestClient, guard_network):
    """Handle network timeout during token exchange cleanly."""
    auth_res = oauth_test_client.get("/api/auth/google-chat/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Token request timed out")

        res = oauth_test_client.get(f"/api/auth/google-chat/callback?code=code_1&state={state}")
        assert res.status_code == 400
        assert "Network timeout" in res.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. Status & Disconnect Endpoints
# ═══════════════════════════════════════════════════════════════════════════


def test_status_endpoint_lifecycle(
    oauth_test_client: TestClient,
    memory_token_storage: InMemoryTokenStorage,
    guard_network,
):
    """Verify status reports state changes accurately and never exposes secrets."""
    # 1. Initially not connected
    s1 = oauth_test_client.get("/api/auth/google-chat/status").json()
    assert s1["configured"] is True
    assert s1["connected"] is False
    assert s1["has_refresh_token"] is False
    assert s1["default_space"] == "spaces/DEFAULT_FALLBACK"

    # 2. Store valid token
    memory_token_storage.save_token(
        OAuthToken(
            access_token="acc_tok",
            refresh_token="ref_tok",
            expires_at=time.time() + 3600,
        )
    )

    s2 = oauth_test_client.get("/api/auth/google-chat/status").json()
    assert s2["connected"] is True
    assert s2["is_expired"] is False
    assert s2["has_refresh_token"] is True
    assert s2["expires_at"] is not None

    # Verify secrets are NOT in status response
    s2_str = json.dumps(s2)
    assert "acc_tok" not in s2_str
    assert "ref_tok" not in s2_str
    assert "test_super_secret" not in s2_str

    # 3. Disconnect
    dis_res = oauth_test_client.post("/api/auth/google-chat/disconnect")
    assert dis_res.status_code == 200
    assert dis_res.json()["status"] == "disconnected"

    s3 = oauth_test_client.get("/api/auth/google-chat/status").json()
    assert s3["connected"] is False
    assert memory_token_storage.load_token() is None


# ═══════════════════════════════════════════════════════════════════════════
# 6. Professor Space Routing Endpoints
# ═══════════════════════════════════════════════════════════════════════════


def test_spaces_management_flow(
    oauth_test_client: TestClient,
    sample_subject: Subject,
    guard_network,
):
    """Verify professor Google Chat space configuration endpoints."""
    # 1. List spaces (sample_subject has no space configured yet)
    res_list = oauth_test_client.get("/api/auth/google-chat/spaces")
    assert res_list.status_code == 200
    data = res_list.json()
    assert data["default_space"] == "spaces/DEFAULT_FALLBACK"
    assert len(data["mappings"]) >= 1

    cs101_map = next(m for m in data["mappings"] if m["subject_code"] == "CS101")
    assert cs101_map["google_chat_space"] is None
    assert cs101_map["is_configured"] is False

    # 2. Update space for CS101
    put_res = oauth_test_client.put(
        "/api/auth/google-chat/spaces/CS101",
        json={"google_chat_space": "spaces/TURING_ROOM"},
    )
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["google_chat_space"] == "spaces/TURING_ROOM"
    assert updated["is_configured"] is True

    # 3. Verify in status mappings count
    status_data = oauth_test_client.get("/api/auth/google-chat/status").json()
    assert status_data["recipient_mappings_count"] == 1

    # 4. Clear space (safe unconfigured state)
    clear_res = oauth_test_client.put(
        "/api/auth/google-chat/spaces/CS101",
        json={"google_chat_space": None},
    )
    assert clear_res.status_code == 200
    cleared = clear_res.json()
    assert cleared["google_chat_space"] is None
    assert cleared["is_configured"] is False

    # 5. Non-existent subject returns 404
    err_res = oauth_test_client.put(
        "/api/auth/google-chat/spaces/NOT_EXIST",
        json={"google_chat_space": "spaces/FOO"},
    )
    assert err_res.status_code == 404

    # 6. Update default space
    def_res = oauth_test_client.put(
        "/api/auth/google-chat/default-space",
        json={"default_space": "spaces/CUSTOM_DEFAULT"},
    )
    assert def_res.status_code == 200
    assert def_res.json()["default_space"] == "spaces/CUSTOM_DEFAULT"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Dashboard and Static Assets Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_dashboard_and_static_files(oauth_test_client: TestClient, guard_network):
    """Verify /dashboard and static assets are served properly."""
    res_dash = oauth_test_client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "Attendance Automation Dashboard" in res_dash.text
    assert "app-shell" in res_dash.text

    res_css = oauth_test_client.get("/static/css/style.css")
    assert res_css.status_code == 200
    assert "--accent-primary" in res_css.text

    res_js = oauth_test_client.get("/static/js/main.js")
    assert res_js.status_code == 200
    assert "AppRouter" in res_js.text

    # Root endpoint includes dashboard_url
    res_root = oauth_test_client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "online"
    assert res_root.json()["dashboard_url"] == "/dashboard"


def test_callback_browser_redirect_success(oauth_test_client: TestClient, guard_network):
    """Verify that browser visits with Accept: text/html or redirect=true redirect to /#settings?oauth_success=google_chat."""
    auth_res = oauth_test_client.get("/api/auth/google-chat/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "mock_access_tok_redirect",
            "refresh_token": "mock_refresh_tok_redirect",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/chat.messages.create",
        }
        mock_post.return_value = mock_resp

        res = oauth_test_client.get(
            f"/api/auth/google-chat/callback?code=mock_code&state={state}&redirect=true",
            follow_redirects=False,
        )
        assert res.status_code == 307
        assert res.headers.get("location") == "/#settings?oauth_success=google_chat"


def test_callback_browser_redirect_error(oauth_test_client: TestClient, guard_network):
    """Verify that callback errors with redirect=true redirect to /#settings?oauth_error=true."""
    res = oauth_test_client.get(
        "/api/auth/google-chat/callback?error=access_denied&redirect=true",
        follow_redirects=False,
    )
    assert res.status_code == 307
    assert res.headers.get("location") == "/#settings?oauth_error=true"

