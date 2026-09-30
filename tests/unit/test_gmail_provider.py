import datetime
from unittest.mock import MagicMock

import pytest
import httpx

from app.notifications.base import (
    NotificationConfigError,
    NotificationDeliveryError,
    NotificationOutcome,
    NotificationPayload,
    NotificationProviderError,
)
from app.notifications.gmail.client import GmailClient
from app.notifications.gmail.config import GmailConfig
from app.notifications.gmail.provider import GmailNotificationProvider
from app.notifications.oauth import (
    InMemoryTokenStorage,
    OAuthAuthenticationError,
    OAuthConfigurationError,
    OAuthToken,
)


@pytest.fixture
def gmail_config() -> GmailConfig:
    return GmailConfig(
        client_id="test_client",
        client_secret="test_secret",
        redirect_uri="http://localhost:8000/callback",
        sender_email="me@example.com",
    )


@pytest.fixture
def mock_oauth_client() -> MagicMock:
    client = MagicMock()
    client.get_valid_access_token.return_value = "mock_access_token"
    client.refresh_access_token.return_value = OAuthToken(
        access_token="refreshed_access_token",
        refresh_token="mock_refresh_token",
        expires_at=2000000000.0,
    )
    return client


@pytest.fixture
def mock_http_client() -> MagicMock:
    client = MagicMock(spec=httpx.Client)
    return client


@pytest.fixture
def gmail_client(
    gmail_config: GmailConfig,
    mock_oauth_client: MagicMock,
    mock_http_client: MagicMock,
) -> GmailClient:
    return GmailClient(config=gmail_config, oauth_client=mock_oauth_client, http_client=mock_http_client)


@pytest.fixture
def provider(gmail_client: GmailClient) -> GmailNotificationProvider:
    return GmailNotificationProvider(client=gmail_client, is_dry_run=False)


def test_gmail_client_send_success(gmail_client: GmailClient, mock_http_client: MagicMock):
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "12345", "threadId": "12345"}
    mock_http_client.post.return_value = mock_response

    result = gmail_client.send_email(
        recipient_email="prof@example.com",
        subject="Test Subject",
        body="Test Body",
    )

    assert result["id"] == "12345"
    mock_http_client.post.assert_called_once()

    # Assert headers contain auth
    kwargs = mock_http_client.post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer mock_access_token"
    assert "raw" in kwargs["json"]


def test_gmail_client_api_error(gmail_client: GmailClient, mock_http_client: MagicMock):
    # Mock error response
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"error": {"message": "Bad Request"}}
    mock_http_client.post.return_value = mock_response

    with pytest.raises(NotificationProviderError, match="Bad Request"):
        gmail_client.send_email(
            recipient_email="prof@example.com",
            subject="Test Subject",
            body="Test Body",
        )


def test_gmail_client_network_error(gmail_client: GmailClient, mock_http_client: MagicMock):
    mock_http_client.post.side_effect = httpx.TimeoutException("Timeout")

    with pytest.raises(NotificationProviderError, match="Network timeout"):
        gmail_client.send_email(
            recipient_email="prof@example.com",
            subject="Test Subject",
            body="Test Body",
        )


def test_gmail_client_401_refresh_retry_success(
    gmail_client: GmailClient,
    mock_oauth_client: MagicMock,
    mock_http_client: MagicMock,
):
    """When Gmail API returns 401, client attempts refresh and retries once."""
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_resp_401.json.return_value = {"error": {"message": "Invalid Credentials"}}

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"id": "refreshed_msg_1", "threadId": "th_1"}

    mock_http_client.post.side_effect = [mock_resp_401, mock_resp_200]

    result = gmail_client.send_email(
        recipient_email="prof@example.com",
        subject="Test Subject",
        body="Test Body",
    )

    assert result["id"] == "refreshed_msg_1"
    assert mock_oauth_client.refresh_access_token.called
    assert mock_http_client.post.call_count == 2
    # Verify second call used refreshed access token
    second_call_headers = mock_http_client.post.call_args_list[1].kwargs["headers"]
    assert second_call_headers["Authorization"] == "Bearer refreshed_access_token"


def test_gmail_client_401_refresh_retry_failure(
    gmail_client: GmailClient,
    mock_oauth_client: MagicMock,
    mock_http_client: MagicMock,
):
    """When refresh fails following 401, client raises NotificationProviderError."""
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_resp_401.json.return_value = {"error": {"message": "Invalid Credentials"}}
    mock_http_client.post.return_value = mock_resp_401

    mock_oauth_client.refresh_access_token.side_effect = OAuthAuthenticationError("Token revoked")

    with pytest.raises(NotificationProviderError, match="unauthorized and refresh failed"):
        gmail_client.send_email(
            recipient_email="prof@example.com",
            subject="Test Subject",
            body="Test Body",
        )


def test_gmail_client_invalid_recipient_validation(gmail_client: GmailClient):
    """Recipient without @ must fail validation without network request."""
    with pytest.raises(NotificationProviderError, match="Invalid recipient"):
        gmail_client.send_email(
            recipient_email="not-an-email",
            subject="Subj",
            body="Body",
        )


def test_gmail_client_auth_error_on_missing_token(
    gmail_config: GmailConfig,
    mock_http_client: MagicMock,
):
    """When oauth client raises OAuthAuthenticationError, client wraps safely."""
    mock_oauth = MagicMock()
    mock_oauth.get_valid_access_token.side_effect = OAuthAuthenticationError("No token found")
    client = GmailClient(config=gmail_config, oauth_client=mock_oauth, http_client=mock_http_client)

    with pytest.raises(NotificationProviderError, match="Gmail authorization error"):
        client.send_email(
            recipient_email="prof@example.com",
            subject="Subj",
            body="Body",
        )


def test_gmail_provider_dry_run(gmail_client: GmailClient, mock_http_client: MagicMock):
    provider = GmailNotificationProvider(client=gmail_client, is_dry_run=True)
    payload = NotificationPayload(
        subject_code="CS101",
        subject_name="Intro to CS",
        target_date=datetime.date(2026, 9, 29),
        recipient_email="prof@example.com",
        professor_name="Dr. Smith",
        message_subject="Test Subject",
        message_body="Test Body",
        student_name="Student",
    )

    outcome = provider.send(payload)

    assert outcome.success is True
    assert outcome.is_dry_run is True
    assert outcome.provider_name == "gmail"
    # Ensure network was NOT called
    mock_http_client.post.assert_not_called()


def test_gmail_provider_real_send_success(provider: GmailNotificationProvider, mock_http_client: MagicMock):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "message_999"}
    mock_http_client.post.return_value = mock_response

    payload = NotificationPayload(
        subject_code="CS101",
        subject_name="Intro to CS",
        target_date=datetime.date(2026, 9, 29),
        recipient_email="prof@example.com",
        professor_name="Dr. Smith",
        message_subject="Test Subject",
        message_body="Test Body",
        student_name="Student",
    )

    outcome = provider.send(payload)

    assert outcome.success is True
    assert outcome.is_dry_run is False
    assert outcome.details.get("external_id") == "message_999"


def test_gmail_provider_real_send_failure(provider: GmailNotificationProvider, mock_http_client: MagicMock):
    mock_http_client.post.side_effect = httpx.TimeoutException("Timeout")

    payload = NotificationPayload(
        subject_code="CS101",
        subject_name="Intro to CS",
        target_date=datetime.date(2026, 9, 29),
        recipient_email="prof@example.com",
        professor_name="Dr. Smith",
        message_subject="Test Subject",
        message_body="Test Body",
        student_name="Student",
    )

    with pytest.raises(NotificationDeliveryError):
        provider.send(payload)


def test_gmail_provider_invalid_recipient_format(provider: GmailNotificationProvider):
    payload = NotificationPayload(
        subject_code="CS101",
        subject_name="Intro to CS",
        target_date=datetime.date(2026, 9, 29),
        recipient_email="notanemail",
        professor_name="Dr. Smith",
        message_subject="Test Subject",
        message_body="Test Body",
        student_name="Student",
    )
    with pytest.raises(NotificationDeliveryError, match="Invalid recipient email"):
        provider.send(payload)


def test_gmail_provider_validate_config(gmail_client: GmailClient):
    provider = GmailNotificationProvider(client=gmail_client)
    assert provider.validate_config() is True

    # Invalid config
    bad_config = GmailConfig(client_id=None, client_secret=None)
    bad_client = GmailClient(config=bad_config, oauth_client=MagicMock())
    bad_provider = GmailNotificationProvider(client=bad_client)
    with pytest.raises(NotificationConfigError):
        bad_provider.validate_config()


def test_gmail_provider_init_from_config(gmail_config: GmailConfig):
    storage = InMemoryTokenStorage()
    provider = GmailNotificationProvider(config=gmail_config, token_storage=storage, is_dry_run=True)
    assert provider.provider_name == "gmail"
    assert provider.is_dry_run is True
    assert provider.validate_config() is True


def test_gmail_config_safe_dict_and_repr(gmail_config: GmailConfig):
    safe = gmail_config.safe_dict()
    assert safe["client_secret"] == "[REDACTED]"
    assert safe["client_id"] == "test_client"
    assert "test_secret" not in repr(gmail_config)
    assert "[REDACTED]" in repr(gmail_config)
