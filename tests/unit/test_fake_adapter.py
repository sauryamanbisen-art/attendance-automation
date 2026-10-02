"""Unit tests for FakePortalAdapter."""

from datetime import date

import pytest

from app.adapters.base.adapter import (
    PortalAuthenticationError,
    PortalUnavailableError,
    SubjectAttendance,
)
from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario
from app.core.enums import AttendanceStatus


def test_fake_adapter_python_present() -> None:
    """Test scenario: Python -> PRESENT."""
    adapter = FakePortalAdapter(scenario=FakeScenario.PYTHON_PRESENT)
    assert adapter.validate_config() is True
    assert adapter.authenticate() is True

    records = adapter.get_attendance_for_date(date(2026, 9, 25))
    assert len(records) == 1
    assert records[0].subject_code == "303PDS"
    assert records[0].status == AttendanceStatus.PRESENT
    assert records[0].is_reliable is True

    adapter.close()
    assert adapter.is_closed is True


def test_fake_adapter_python_absent() -> None:
    """Test scenario: Python -> ABSENT."""
    adapter = FakePortalAdapter(scenario=FakeScenario.PYTHON_ABSENT)
    records = adapter.get_attendance_for_date(date(2026, 9, 25))

    assert len(records) == 1
    assert records[0].subject_code == "303PDS"
    assert records[0].status == AttendanceStatus.ABSENT
    assert records[0].is_reliable is True


def test_fake_adapter_unreliable_absent() -> None:
    """Test scenario: Unreliable ABSENT -> is_reliable=False."""
    adapter = FakePortalAdapter(scenario=FakeScenario.UNRELIABLE_ABSENT)
    records = adapter.get_attendance_for_date(date(2026, 9, 25))

    assert len(records) == 1
    assert records[0].subject_code == "303PDS"
    assert records[0].status == AttendanceStatus.ABSENT
    assert records[0].is_reliable is False
    assert "warning" in records[0].metadata


def test_fake_adapter_python_unknown() -> None:
    """Test scenario: Python -> UNKNOWN."""
    adapter = FakePortalAdapter(scenario=FakeScenario.PYTHON_UNKNOWN)
    records = adapter.get_attendance_for_date(date(2026, 9, 25))

    assert len(records) == 1
    assert records[0].subject_code == "303PDS"
    assert records[0].status == AttendanceStatus.UNKNOWN
    assert records[0].is_reliable is True


def test_fake_adapter_mixed_scenario() -> None:
    """Test scenario: multiple subjects with mixed statuses."""
    adapter = FakePortalAdapter(scenario=FakeScenario.MIXED)
    records = adapter.get_attendance_for_date(date(2026, 9, 25))

    assert len(records) == 3
    by_code = {r.subject_code: r for r in records}

    assert by_code["303PDS"].status == AttendanceStatus.ABSENT
    assert by_code["301ADS"].status == AttendanceStatus.PRESENT
    assert by_code["302OPS"].status == AttendanceStatus.UNKNOWN


def test_fake_adapter_portal_unavailable() -> None:
    """Test scenario: portal unavailable raises PortalUnavailableError."""
    adapter = FakePortalAdapter(scenario=FakeScenario.PORTAL_UNAVAILABLE)

    with pytest.raises(PortalUnavailableError, match="outage"):
        adapter.get_attendance_for_date(date(2026, 9, 25))


def test_fake_adapter_malformed_response() -> None:
    """Test scenario: malformed response fails closed to UNKNOWN with is_reliable=False."""
    adapter = FakePortalAdapter(scenario=FakeScenario.MALFORMED_RESPONSE)
    records = adapter.get_attendance_for_date(date(2026, 9, 25))

    assert len(records) == 1
    assert records[0].status == AttendanceStatus.UNKNOWN
    assert records[0].is_reliable is False
    assert "error" in records[0].metadata


def test_fake_adapter_ambiguous_response() -> None:
    """Test scenario: ambiguous response normalizes to UNKNOWN with is_reliable=False."""
    adapter = FakePortalAdapter(scenario=FakeScenario.AMBIGUOUS_RESPONSE)
    records = adapter.get_attendance_for_date(date(2026, 9, 25))

    assert len(records) == 1
    assert records[0].status == AttendanceStatus.UNKNOWN
    assert records[0].is_reliable is False


def test_fake_adapter_status_normalization() -> None:
    """Test status normalization across raw representations."""
    adapter = FakePortalAdapter()

    # Present representations
    assert adapter.normalize_status("Present") == AttendanceStatus.PRESENT
    assert adapter.normalize_status("present") == AttendanceStatus.PRESENT
    assert adapter.normalize_status("P") == AttendanceStatus.PRESENT
    assert adapter.normalize_status("attended") == AttendanceStatus.PRESENT

    # Absent representations
    assert adapter.normalize_status("Absent") == AttendanceStatus.ABSENT
    assert adapter.normalize_status("absent") == AttendanceStatus.ABSENT
    assert adapter.normalize_status("A") == AttendanceStatus.ABSENT
    assert adapter.normalize_status("unexcused") == AttendanceStatus.ABSENT

    # Ambiguous or unknown representations fail closed to UNKNOWN
    assert adapter.normalize_status(None) == AttendanceStatus.UNKNOWN
    assert adapter.normalize_status("") == AttendanceStatus.UNKNOWN
    assert adapter.normalize_status("TBD") == AttendanceStatus.UNKNOWN
    assert adapter.normalize_status("Pending") == AttendanceStatus.UNKNOWN
    assert adapter.normalize_status("Exempt") == AttendanceStatus.UNKNOWN
    assert adapter.normalize_status("Medical Leave") == AttendanceStatus.UNKNOWN


def test_fake_adapter_auth_failure() -> None:
    """Test authentication failure simulation."""
    adapter = FakePortalAdapter(is_auth_success=False)
    with pytest.raises(PortalAuthenticationError):
        adapter.authenticate()


def test_fake_adapter_custom_subjects() -> None:
    """Test custom subject overrides."""
    adapter = FakePortalAdapter()
    custom = [
        SubjectAttendance(subject_code="MATH101", status=AttendanceStatus.PRESENT, is_reliable=True),
        SubjectAttendance(subject_code="ENG102", status=AttendanceStatus.ABSENT, is_reliable=True),
    ]
    adapter.set_custom_subjects(custom)
    records = adapter.get_attendance_for_date(date(2026, 9, 25))
    assert records == custom


def test_subject_attendance_requires_explicit_reliability() -> None:
    """SubjectAttendance must raise TypeError if is_reliable is omitted."""
    with pytest.raises(TypeError):
        SubjectAttendance(subject_code="PHYS101", status=AttendanceStatus.ABSENT)  # type: ignore[call-arg]
