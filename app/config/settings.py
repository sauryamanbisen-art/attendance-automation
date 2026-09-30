"""Application configuration via Pydantic Settings."""

from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.security.redaction import redact_data


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Attendance Automation Platform"
    app_env: str = "development"
    log_level: str = "INFO"
    timezone: str = "Asia/Kolkata"
    cutoff_time: str = "16:00"
    dry_run: bool = True

    # Database
    database_url: str = "sqlite:///./attendance.db"

    # Portal Adapter
    portal_adapter: str = "pwioi"
    portal_url: str = "https://portal.example.edu"
    portal_username: str = "demo_student"
    portal_password: str | None = None
    portal_auth_mode: str = "password"
    portal_headless: bool = True
    portal_timeout_ms: int = 15000
    portal_browser_channel: str | None = None
    portal_storage_state: str = "storage_state/portal_session.json"

    # PWIOI Portal Adapter Settings
    pwioi_portal_url: str = "https://app.pwioi.club/auth/student/login"
    pwioi_attendance_url: str = "https://app.pwioi.club/dashboard/student/attendance"
    pwioi_academic_term: str | None = None
    pwioi_storage_state: str = "storage_state/pwioi_session.json"
    pwioi_browser_channel: str | None = None
    pwioi_manual_login_timeout_ms: int = 300000

    # Email / Notification Provider
    email_provider: str = "dry_run"
    notification_sender_email: str = "student@example.edu"
    gmail_client_id: str | None = None
    gmail_client_secret: str | None = None
    gmail_redirect_uri: str = "http://localhost:8000/api/auth/gmail/callback"
    gmail_token_file: str | None = None

    # Google Chat / OAuth Settings
    google_chat_client_id: str | None = None
    google_chat_client_secret: str | None = None
    google_chat_redirect_uri: str = "http://localhost:8000/api/auth/google-chat/callback"
    google_chat_token_file: str | None = None
    google_chat_default_space: str | None = None

    def safe_dict(self) -> dict[str, Any]:
        """Return a copy of settings with all sensitive values redacted."""
        return redact_data(self.model_dump())


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
