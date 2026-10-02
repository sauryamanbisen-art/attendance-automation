"""Pydantic schemas for API request and response models."""

from datetime import date as date_type
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AttendanceStatus, CheckStatus, DecisionAction, DecisionReason


class ConfirmationCreate(BaseModel):
    """Request payload to confirm attendance."""

    date: date_type = Field(description="Date being confirmed (YYYY-MM-DD)")
    note: Optional[str] = Field(default=None, max_length=255, description="Optional note")


class ConfirmationResponse(BaseModel):
    """Response payload for attendance confirmation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date_type
    confirmed_at: datetime
    note: Optional[str]
    created: bool = Field(description="True if newly created; False if already confirmed")


class ProfessorMappingSchema(BaseModel):
    """Schema for professor mapping details."""

    model_config = ConfigDict(from_attributes=True)

    professor_name: str = Field(min_length=1, max_length=150)
    professor_email: str = Field(
        min_length=3,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Valid professor email address",
    )
    google_chat_space: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional Google Chat space or DM resource name, e.g. spaces/AAAA123",
    )
    is_active: bool = Field(
        default=True,
        description="Whether automated notifications are enabled for this professor mapping",
    )


class SubjectCreate(BaseModel):
    """Payload to register a new subject with optional professor mapping."""

    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    professor_name: Optional[str] = Field(default=None, max_length=150)
    professor_email: Optional[str] = Field(
        default=None,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Valid professor email address",
    )
    google_chat_space: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional Google Chat space or DM resource name",
    )
    is_active: Optional[bool] = Field(
        default=True,
        description="Whether automated notifications are enabled for this professor mapping",
    )


class SubjectResponse(BaseModel):
    """Response payload for a registered subject."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    professor_name: Optional[str] = None
    professor_email: Optional[str] = None
    google_chat_space: Optional[str] = None
    is_active: Optional[bool] = None
    academic_rate: Optional[float] = None
    attended_classes: Optional[int] = None
    total_classes: Optional[int] = None


class CheckRunRequest(BaseModel):
    """Payload to trigger an attendance check."""

    date: Optional[date_type] = Field(default=None, description="Target check date")
    scenario: Optional[str] = Field(default=None, description="Fake adapter scenario if using fake adapter")


class SubjectResultItem(BaseModel):
    """Individual subject attendance status inside a check response."""

    subject_code: str
    status: AttendanceStatus
    raw_status: Optional[str] = None
    is_reliable: bool = True


class DecisionItem(BaseModel):
    """Individual decision outcome for a subject."""

    action: DecisionAction
    reason: DecisionReason
    subject_code: str
    target_date: date_type
    is_confirmed: bool
    status: AttendanceStatus
    is_reliable: bool = True
    professor_email: Optional[str] = None


class CheckRunResponse(BaseModel):
    """Result of an attendance check and decision evaluation."""

    run_id: str
    check_date: date_type
    adapter_name: str
    status: CheckStatus
    results: List[SubjectResultItem]
    decisions: List[DecisionItem]
    error_message: Optional[str] = None


class AuditEventResponse(BaseModel):
    """Response payload for audit log query."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    event_type: str
    action: str
    entity_type: str
    entity_id: Optional[str]
    details: dict[str, Any]
    timestamp: datetime


class GoogleChatStatusResponse(BaseModel):
    """Safe status report for Google Chat OAuth connection and spaces."""

    configured: bool = Field(description="True if OAuth client_id and client_secret are provided")
    connected: bool = Field(description="True if valid or refreshable token is stored locally")
    is_expired: bool = Field(description="True if token is expired")
    has_refresh_token: bool = Field(description="True if token contains a refresh token")
    expires_at: Optional[float] = Field(default=None, description="Unix timestamp of token expiration")
    default_space: Optional[str] = Field(default=None, description="Configured default space fallback")
    scopes: List[str] = Field(default_factory=list, description="Authorized OAuth scopes")
    dry_run: bool = Field(description="True if dry run safe mode is active")
    recipient_mappings_count: int = Field(description="Number of configured professor space mappings")
    client_id_configured: bool = Field(description="True if client_id is set")


class GoogleChatAuthorizeResponse(BaseModel):
    """Response payload for OAuth authorization initiation."""

    authorization_url: str = Field(description="Google OAuth 2.0 authorization URL")
    state: str = Field(description="CSRF state token")


class GoogleChatCallbackResponse(BaseModel):
    """Safe response payload after successful OAuth callback."""

    status: str = Field(description="Connection status (e.g. 'connected')")
    message: str = Field(description="User-facing status message")
    scope: Optional[str] = Field(default=None, description="Granted OAuth scope")
    expires_at: Optional[float] = Field(default=None, description="Token expiration timestamp")


class GmailAuthorizeResponse(BaseModel):
    """Response payload for Gmail OAuth authorization initiation."""

    authorization_url: str = Field(description="Google OAuth 2.0 authorization URL for Gmail")
    state: str = Field(description="CSRF state token")


class GmailCallbackResponse(BaseModel):
    """Safe response payload after successful Gmail OAuth callback."""

    status: str = Field(description="Connection status (e.g. 'connected')")
    message: str = Field(description="User-facing status message")
    scope: Optional[str] = Field(default=None, description="Granted OAuth scope")
    expires_at: Optional[float] = Field(default=None, description="Token expiration timestamp")


class ProfessorSpaceMappingItem(BaseModel):
    """Professor and Google Chat space mapping entry."""

    subject_code: str
    subject_name: str
    professor_name: Optional[str] = None
    professor_email: Optional[str] = None
    google_chat_space: Optional[str] = None
    is_configured: bool = Field(description="True if Google Chat space is set for this professor")
    is_active: bool = Field(default=True, description="Whether professor mapping notifications are enabled")


class SpaceMappingUpdateRequest(BaseModel):
    """Request to update a professor's Google Chat space."""

    google_chat_space: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Google Chat space ID (e.g. spaces/AAAA123) or null to leave unconfigured",
    )


class DefaultSpaceUpdateRequest(BaseModel):
    """Request to update the fallback default Google Chat space."""

    default_space: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Default space name (e.g. spaces/DEFAULT) or null to clear",
    )


class DiscoverDmRequest(BaseModel):
    """Request payload to discover a professor's Google Chat direct message space."""

    professor_email: str = Field(
        min_length=3,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Valid professor email address to discover Google Chat DM space for",
    )
    subject_code: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Optional subject code to associate with discovered space",
    )


class DiscoverDmResponse(BaseModel):
    """Response payload containing discovered Google Chat DM space."""

    space: str = Field(description="Resolved Google Chat space resource name (e.g. spaces/AAAA123)")
    professor_email: str = Field(description="Professor email address")
    subject_code: Optional[str] = Field(default=None, description="Targeted subject code if provided")
    updated_subjects: List[str] = Field(
        default_factory=list,
        description="List of subject codes whose mappings were updated with this space",
    )
    message: str = Field(description="User-facing summary message")


from datetime import time as time_type
from app.models.calendar import ExceptionType

class TimetableSlotCreate(BaseModel):
    subject_id: int
    weekday: int = Field(ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: time_type
    end_time: time_type
    period_name: Optional[str] = None
    valid_from: Optional[date_type] = None
    valid_to: Optional[date_type] = None

class TimetableSlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_id: int
    weekday: int
    start_time: time_type
    end_time: time_type
    period_name: Optional[str] = None
    valid_from: Optional[date_type] = None
    valid_to: Optional[date_type] = None

class HolidayCreate(BaseModel):
    date: date_type
    description: str = Field(min_length=1, max_length=200)

class HolidayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    date: date_type
    description: str

class ClassExceptionCreate(BaseModel):
    subject_id: int
    date: date_type
    exception_type: ExceptionType
    start_time: Optional[time_type] = None
    end_time: Optional[time_type] = None
    description: Optional[str] = None

class ClassExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_id: int
    date: date_type
    exception_type: ExceptionType
    start_time: Optional[time_type] = None
    end_time: Optional[time_type] = None
    description: Optional[str] = None

class DashboardResponse(BaseModel):
    today: date_type
    is_holiday: bool
    is_confirmed: bool
    expected_classes: List[SubjectResponse]
    attendance_records: List[SubjectResultItem]
    academic_attendance_rate: Optional[float] = None
    academic_attended_classes: Optional[int] = None
    academic_total_classes: Optional[int] = None
    academic_sync_status: Optional[str] = "AWAITING_PORTAL_SYNC"


class HistoryItem(BaseModel):
    check_id: int
    run_id: str
    check_date: date_type
    subject_code: str
    subject_name: Optional[str] = None
    status: AttendanceStatus
    raw_status: Optional[str] = None
    is_reliable: bool
    notes: Optional[str] = None
    is_holiday: bool = False
    is_cancelled: bool = False
    is_extra: bool = False
    is_scheduled: bool = False
    notification_status: Optional[str] = None
    notification_dry_run: Optional[bool] = None

class HistoryResponse(BaseModel):
    items: List[HistoryItem]
    total: int
    limit: int
    offset: int

class SettingsResponse(BaseModel):
    app_name: str
    app_env: str
    log_level: str
    timezone: str
    dry_run: bool
    portal_adapter: str
    portal_headless: bool
    portal_browser_channel: Optional[str]
    email_provider: str
    notification_sender_email: str
    pwioi_academic_term: Optional[str]

class ProviderStatus(BaseModel):
    id: str
    name: str
    connected: bool
    is_configured: bool
    auth_url: Optional[str] = None
    account_identifier: Optional[str] = None

class NotificationProvidersResponse(BaseModel):
    providers: List[ProviderStatus]

class SessionStatusResponse(BaseModel):
    is_authenticated: bool
    session_file_exists: bool
    message: str
    student_name: Optional[str] = None
    student_email: Optional[str] = None
    enrollment_id: Optional[str] = None

