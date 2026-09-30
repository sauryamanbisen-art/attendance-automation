"""Unit tests for secret redaction and logging security."""

import logging
import os
import stat

from app.config.settings import Settings
from app.core.logging import RedactingFormatter
from app.notifications.oauth import FileTokenStorage, OAuthToken
from app.security.redaction import redact_data, redact_string


def test_redact_string_bearer_and_secrets() -> None:
    """Test string redaction for auth headers and parameters."""
    raw = "Request with Bearer ya29.a0AfH6SMCxyz123 and token=supersecretpassword"
    cleaned = redact_string(raw)
    assert "ya29" not in cleaned
    assert "supersecretpassword" not in cleaned
    assert "[REDACTED]" in cleaned


def test_redact_data_dictionary() -> None:
    """Test recursive data dictionary redaction."""
    payload = {
        "username": "student_01",
        "portal_password": "PlaintextPassword123!",
        "auth_token": "secret_token_abc",
        "nested": {
            "api_key": "xyz987",
            "safe_field": "public_value",
            "session_cookie": "sess_12345",
        },
        "list_items": [
            {"password": "hidden_pw", "name": "item1"},
        ],
    }
    safe = redact_data(payload)

    assert safe["username"] == "student_01"
    assert safe["portal_password"] == "[REDACTED]"
    assert safe["auth_token"] == "[REDACTED]"
    assert safe["nested"]["api_key"] == "[REDACTED]"
    assert safe["nested"]["safe_field"] == "public_value"
    assert safe["nested"]["session_cookie"] == "[REDACTED]"
    assert safe["list_items"][0]["password"] == "[REDACTED]"
    assert safe["list_items"][0]["name"] == "item1"


def test_redacting_formatter() -> None:
    """Test logging formatter masks sensitive patterns."""
    formatter = RedactingFormatter(fmt="%(message)s")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Connecting with password=VerySecretValue!",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "VerySecretValue!" not in formatted
    assert "[REDACTED]" in formatted


def test_settings_safe_dict_redaction() -> None:
    """Verify Settings.safe_dict() never leaks passwords or secrets."""
    settings = Settings(
        portal_password="SuperSecretPortalPassword",
        gmail_client_secret="GoogleClientSecret456",
    )
    safe = settings.safe_dict()
    assert safe["portal_password"] == "[REDACTED]"
    assert safe["gmail_client_secret"] == "[REDACTED]"
    assert safe["portal_adapter"] == "pwioi"


def test_oauth_token_and_headers_redaction() -> None:
    """Verify OAuthToken repr and string formatting NEVER reveal tokens."""
    from app.notifications.google_chat.oauth import OAuthToken
    token = OAuthToken(
        access_token="ya29.super_secret_access_token_123",
        refresh_token="1//super_secret_refresh_token_456",
        expires_at=2000000000.0,
    )
    repr_str = repr(token)
    str_val = str(token)

    assert "ya29.super_secret_access_token_123" not in repr_str
    assert "1//super_secret_refresh_token_456" not in repr_str
    assert "[REDACTED]" in repr_str

    assert "ya29.super_secret_access_token_123" not in str_val
    assert "1//super_secret_refresh_token_456" not in str_val


def test_logging_formatter_redacts_auth_headers_and_codes() -> None:
    """Verify RedactingFormatter redacts Bearer tokens, codes, and secrets."""
    formatter = RedactingFormatter(fmt="%(message)s")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg="Authorization: Bearer ya29.a0AfH6SMCxyz999 callback with code=4/0AbCdEfGhIjKlMnOpQrStUv",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "ya29.a0AfH6SMCxyz999" not in formatted
    assert "4/0AbCdEfGhIjKlMnOpQrStUv" not in formatted
    assert "[REDACTED]" in formatted


def test_file_token_storage_permissions(tmp_path) -> None:
    """Verify FileTokenStorage enforces 0700 directory and 0600 file permissions."""
    token_dir = tmp_path / "secret_oauth_dir"
    token_file = token_dir / "tokens.json"

    storage = FileTokenStorage(str(token_file))
    token = OAuthToken(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_at=2000000000.0,
    )
    storage.save_token(token)

    assert os.path.exists(token_file)

    # Verify POSIX file permissions
    file_mode = stat.S_IMODE(os.stat(token_file).st_mode)
    assert file_mode == 0o600, f"Expected 0600 file permissions, got {oct(file_mode)}"

    dir_mode = stat.S_IMODE(os.stat(token_dir).st_mode)
    assert dir_mode == 0o700, f"Expected 0700 dir permissions, got {oct(dir_mode)}"

    # Verify loading still works cleanly
    loaded = storage.load_token()
    assert loaded is not None
    assert loaded.access_token == "test_access_token"
    assert loaded.refresh_token == "test_refresh_token"


def test_error_messages_redact_secrets() -> None:
    """Verify redact_string cleans sensitive details from error messages."""
    raw_error = "Connection failed: api_key=12345secretKey! with code=oauthCodeABC"
    cleaned = redact_string(raw_error)
    assert "12345secretKey!" not in cleaned
    assert "oauthCodeABC" not in cleaned
    assert "[REDACTED]" in cleaned


