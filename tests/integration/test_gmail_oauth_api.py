"""Integration tests for Gmail OAuth endpoints and notification provider integration."""

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
from app.notifications.oauth import (
    InMemoryTokenStorage,
    OAuthStateManager,
    OAuthToken,
    get_oauth_state_manager,
)
from app.services.gmail_oauth_service import GmailOAuthService
from main import app


@pytest.fixture(name="test_state_manager")
def fixture_test_state_manager() -> OAuthStateManager:
    """Fresh in-memory state manager for each test."""
    return OAuthStateManager(ttl_seconds=600)


@pytest.fixture(name="configured_settings")
def fixture_configured_settings() -> Settings:
    """Settings configured with mock Gmail OAuth credentials."""
    return Settings(
        gmail_client_id="test_gmail_client_id_999.apps.googleusercontent.com",
        gmail_client_secret="test_gmail_super_secret_client_key_888",
        gmail_redirect_uri="http://localhost:8000/api/auth/gmail/callback",
        notification_sender_email="student@university.edu",
        dry_run=True,
    )


@pytest.fixture(name="unconfigured_settings")
def fixture_unconfigured_settings() -> Settings:
    """Settings with no Gmail OAuth credentials and isolated token path."""
    return Settings(
        gmail_client_id=None,
        gmail_client_secret=None,
        gmail_token_file="nonexistent_test_credentials.json",
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
    service = GmailOAuthService(
        settings=configured_settings,
        token_storage=memory_token_storage,
        state_manager=test_state_manager,
    )

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: configured_settings
    app.dependency_overrides[get_oauth_state_manager] = lambda: test_state_manager
    from app.api.gmail import get_gmail_oauth_service

    app.dependency_overrides[get_gmail_oauth_service] = lambda: service

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


def test_gmail_authorize_unconfigured_fails(
    db_session: Session,
    unconfigured_settings: Settings,
    memory_token_storage: InMemoryTokenStorage,
    guard_network,
):
    """When OAuth client credentials are not configured, /authorize returns 400 Bad Request."""
    service = GmailOAuthService(
        settings=unconfigured_settings,
        token_storage=memory_token_storage,
    )
    from app.api.gmail import get_gmail_oauth_service

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: unconfigured_settings
    app.dependency_overrides[get_gmail_oauth_service] = lambda: service

    with TestClient(app) as client:
        res = client.get("/api/auth/gmail/authorize")
        assert res.status_code == 400
        assert "Gmail OAuth is not configured" in res.json()["detail"]

        # Status endpoint reports configured=False
        status_res = client.get("/api/auth/gmail/status")
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["configured"] is False
        assert data["connected"] is False

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Authorize Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_gmail_authorize_json_response(oauth_test_client: TestClient, guard_network):
    """Verify /authorize generates a valid Google authorization URL and tracks CSRF state."""
    res = oauth_test_client.get("/api/auth/gmail/authorize")
    assert res.status_code == 200
    data = res.json()
    assert "authorization_url" in data
    assert "state" in data
    auth_url = data["authorization_url"]
    state = data["state"]

    assert "https://accounts.google.com/o/oauth2/v2/auth" in auth_url
    assert "client_id=test_gmail_client_id_999.apps.googleusercontent.com" in auth_url
    assert f"state={state}" in auth_url
    assert "access_type=offline" in auth_url
    assert "prompt=consent" in auth_url


def test_gmail_authorize_redirect_response(oauth_test_client: TestClient, guard_network):
    """Verify /authorize with redirect=true returns a 307 Temporary Redirect."""
    res = oauth_test_client.get("/api/auth/gmail/authorize?redirect=true", follow_redirects=False)
    assert res.status_code == 307
    location = res.headers.get("location", "")
    assert "https://accounts.google.com/o/oauth2/v2/auth" in location
    assert "client_id=test_gmail_client_id_999.apps.googleusercontent.com" in location


# ═══════════════════════════════════════════════════════════════════════════
# 3. Callback State Validation & User Denial Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_gmail_callback_missing_or_invalid_state(oauth_test_client: TestClient, guard_network):
    """Callback rejects missing or unknown CSRF state tokens."""
    # 1. Missing state
    res1 = oauth_test_client.get("/api/auth/gmail/callback?code=mock_code")
    assert res1.status_code == 400
    assert "state parameter" in res1.json()["detail"].lower()

    # 2. Unknown state
    res2 = oauth_test_client.get("/api/auth/gmail/callback?code=mock_code&state=forged_state_token")
    assert res2.status_code == 400
    assert "invalid or expired" in res2.json()["detail"].lower()


def test_gmail_callback_consumed_state_cannot_be_reused(oauth_test_client: TestClient, guard_network):
    """CSRF state tokens are single-use; reusing a state token must fail."""
    auth_res = oauth_test_client.get("/api/auth/gmail/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "mock_gmail_access_tok_1",
            "refresh_token": "mock_gmail_refresh_tok_1",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.send",
        }
        mock_post.return_value = mock_resp

        # First use succeeds
        res1 = oauth_test_client.get(f"/api/auth/gmail/callback?code=code_1&state={state}")
        assert res1.status_code == 200
        assert res1.json()["status"] == "connected"

        # Replay attempt fails
        res2 = oauth_test_client.get(f"/api/auth/gmail/callback?code=code_2&state={state}")
        assert res2.status_code == 400
        assert "invalid or expired" in res2.json()["detail"].lower()


def test_gmail_callback_denied_authorization(oauth_test_client: TestClient, guard_network):
    """Handle user cancellation or access denied safely without throwing unhandled errors."""
    res = oauth_test_client.get(
        "/api/auth/gmail/callback?error=access_denied&error_description=User+declined+permission"
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "denied or cancelled" in detail.lower()
    assert "declined permission" in detail.lower()


def test_gmail_callback_denied_authorization_browser_redirect(oauth_test_client: TestClient, guard_network):
    """When a browser encounters OAuth denial, redirect safely back to settings without leaking secrets."""
    res = oauth_test_client.get(
        "/api/auth/gmail/callback?error=access_denied&error_description=User+declined+permission&redirect=true",
        follow_redirects=False,
    )
    assert res.status_code == 307
    location = res.headers.get("location", "")
    assert "/#settings" in location
    assert "oauth_error" in location


def test_gmail_callback_missing_code(oauth_test_client: TestClient, guard_network):
    """Callback with valid state but missing authorization code fails cleanly."""
    auth_res = oauth_test_client.get("/api/auth/gmail/authorize")
    state = auth_res.json()["state"]

    res = oauth_test_client.get(f"/api/auth/gmail/callback?state={state}")
    assert res.status_code == 400
    assert "code is missing" in res.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# 4. Token Exchange Success & Failure Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_gmail_callback_token_exchange_success(
    oauth_test_client: TestClient,
    memory_token_storage: InMemoryTokenStorage,
    guard_network,
):
    """Successful OAuth callback exchanges code, stores tokens, and redacts secrets from response."""
    auth_res = oauth_test_client.get("/api/auth/gmail/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ya29.gmail_sensitive_access_xyz",
            "refresh_token": "1//gmail_sensitive_refresh_abc",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.send",
            "token_type": "Bearer",
        }
        mock_post.return_value = mock_resp

        res = oauth_test_client.get(f"/api/auth/gmail/callback?code=mock_gmail_code_123&state={state}")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "connected"
        assert "Credentials stored securely" in data["message"]

        # CRITICAL: Verify secrets are NEVER exposed in the callback response
        res_str = json.dumps(data)
        assert "ya29.gmail_sensitive_access_xyz" not in res_str
        assert "1//gmail_sensitive_refresh_abc" not in res_str
        assert "mock_gmail_code_123" not in res_str
        assert "test_gmail_super_secret" not in res_str

        # Verify token is safely stored
        stored = memory_token_storage.load_token()
        assert stored is not None
        assert stored.access_token == "ya29.gmail_sensitive_access_xyz"
        assert stored.refresh_token == "1//gmail_sensitive_refresh_abc"


def test_gmail_callback_redirect_to_settings_on_success(
    oauth_test_client: TestClient,
    guard_network,
):
    """When redirect=true (browser flow), callback redirects to /#settings?oauth_success=gmail."""
    auth_res = oauth_test_client.get("/api/auth/gmail/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ya29.tok",
            "refresh_token": "1//ref",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.send",
            "token_type": "Bearer",
        }
        mock_post.return_value = mock_resp

        res = oauth_test_client.get(
            f"/api/auth/gmail/callback?code=mock_code&state={state}&redirect=true",
            follow_redirects=False,
        )
        assert res.status_code == 307
        assert res.headers["location"] == "/#settings?oauth_success=gmail"


def test_gmail_callback_token_exchange_server_error(oauth_test_client: TestClient, guard_network):
    """Handle token endpoint error gracefully."""
    auth_res = oauth_test_client.get("/api/auth/gmail/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Code was expired or already redeemed",
        }
        mock_post.return_value = mock_resp

        res = oauth_test_client.get(f"/api/auth/gmail/callback?code=bad_code&state={state}")
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "Code was expired or already redeemed" in detail


def test_gmail_callback_network_timeout(oauth_test_client: TestClient, guard_network):
    """Handle network timeout during token exchange cleanly."""
    auth_res = oauth_test_client.get("/api/auth/gmail/authorize")
    state = auth_res.json()["state"]

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Token request timed out")

        res = oauth_test_client.get(f"/api/auth/gmail/callback?code=code_1&state={state}")
        assert res.status_code == 400
        assert "Network timeout" in res.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. Status, Providers List & Disconnect Endpoints
# ═══════════════════════════════════════════════════════════════════════════


def test_gmail_status_and_providers_lifecycle(
    oauth_test_client: TestClient,
    memory_token_storage: InMemoryTokenStorage,
    guard_network,
):
    """Verify status and provider endpoints report state changes accurately and never expose secrets."""
    # 1. Initially configured but not connected
    s1 = oauth_test_client.get("/api/auth/gmail/status").json()
    assert s1["configured"] is True
    assert s1["connected"] is False
    assert s1["has_refresh_token"] is False

    # Check /api/notifications/providers
    prov1 = oauth_test_client.get("/api/notifications/providers").json()
    gmail_p1 = next(p for p in prov1["providers"] if p["id"] == "gmail")
    assert gmail_p1["is_configured"] is True
    assert gmail_p1["connected"] is False
    assert gmail_p1["account_identifier"] is None
    assert "client_secret" not in json.dumps(gmail_p1)
    assert "token" not in json.dumps(gmail_p1)

    # 2. Store valid token
    memory_token_storage.save_token(
        OAuthToken(
            access_token="valid_acc_tok",
            refresh_token="valid_ref_tok",
            expires_at=time.time() + 3600,
        )
    )

    s2 = oauth_test_client.get("/api/auth/gmail/status").json()
    assert s2["connected"] is True
    assert s2["is_expired"] is False
    assert s2["has_refresh_token"] is True
    assert s2["account_identifier"] == "student@university.edu"

    # Verify secrets are NOT in status response
    s2_str = json.dumps(s2)
    assert "valid_acc_tok" not in s2_str
    assert "valid_ref_tok" not in s2_str
    assert "test_gmail_super_secret" not in s2_str

    # Providers list now reports connected with account identifier
    prov2 = oauth_test_client.get("/api/notifications/providers").json()
    gmail_p2 = next(p for p in prov2["providers"] if p["id"] == "gmail")
    assert gmail_p2["connected"] is True
    assert gmail_p2["account_identifier"] == "student@university.edu"

    # 3. Disconnect via DELETE /api/notifications/gmail/authorization
    del_res = oauth_test_client.delete("/api/notifications/gmail/authorization")
    assert del_res.status_code == 204

    s3 = oauth_test_client.get("/api/auth/gmail/status").json()
    assert s3["connected"] is False
    assert memory_token_storage.load_token() is None

    # Also test POST /api/auth/gmail/disconnect
    memory_token_storage.save_token(OAuthToken(access_token="tok2"))
    dis_res = oauth_test_client.post("/api/auth/gmail/disconnect")
    assert dis_res.status_code == 200
    assert dis_res.json()["status"] == "disconnected"
    assert memory_token_storage.load_token() is None
