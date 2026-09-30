"""Base adapter interfaces and exceptions."""

from app.adapters.base.adapter import (
    BasePortalAdapter,
    PortalAdapterError,
    PortalAuthenticationError,
    PortalParsingError,
    PortalUnavailableError,
    SubjectAttendance,
)

__all__ = [
    "BasePortalAdapter",
    "SubjectAttendance",
    "PortalAdapterError",
    "PortalAuthenticationError",
    "PortalUnavailableError",
    "PortalParsingError",
]
