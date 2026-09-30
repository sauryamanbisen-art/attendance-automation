"""Abstract base class and contract for portal adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, List, Optional

from app.core.enums import AttendanceStatus


class PortalAdapterError(Exception):
    """Base exception for portal adapter failures."""

    pass


class PortalAuthenticationError(PortalAdapterError):
    """Raised when portal authentication fails or requires interactive manual action."""

    pass


class PortalUnavailableError(PortalAdapterError):
    """Raised when the portal is unreachable, times out, or reports maintenance."""

    pass


class PortalParsingError(PortalAdapterError):
    """Raised when portal markup/response is malformed or cannot be parsed."""

    pass


class PortalConfigurationError(PortalAdapterError):
    """Raised when portal adapter configuration is invalid or missing required values."""

    pass


@dataclass(frozen=True)
class SubjectAttendance:
    """Normalized attendance record for a subject on a target date."""

    subject_code: str
    status: AttendanceStatus
    is_reliable: bool
    subject_name: Optional[str] = None
    raw_status: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BasePortalAdapter(ABC):
    """Contract that every college portal adapter must implement."""

    @property
    def adapter_name(self) -> str:
        """Identifier for this adapter implementation."""
        return "base"

    @property
    def is_read_only(self) -> bool:
        """Safety invariant: All adapters in V1 are strictly read-only."""
        return True

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate adapter configuration (e.g. URLs, credentials presence)."""
        pass

    @abstractmethod
    def authenticate(self) -> bool:
        """Authenticate with the college portal or verify an existing session."""
        pass

    @abstractmethod
    def get_attendance_for_date(self, target_date: date) -> List[SubjectAttendance]:
        """Fetch and extract attendance records for the specified date."""
        pass

    @abstractmethod
    def normalize_status(self, raw_status: Optional[str]) -> AttendanceStatus:
        """Normalize raw portal status string to domain AttendanceStatus.

        Any uncertain, unrecognized, or ambiguous string MUST return AttendanceStatus.UNKNOWN.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Clean up resources, browser contexts, and connections."""
        pass

    def __enter__(self) -> "BasePortalAdapter":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

