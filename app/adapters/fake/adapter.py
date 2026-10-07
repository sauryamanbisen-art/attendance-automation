"""Fake portal adapter for testing and offline development without internet access."""

from datetime import date
from enum import Enum
from typing import List, Optional

from app.adapters.base.adapter import (
    BasePortalAdapter,
    PortalAuthenticationError,
    PortalParsingError,
    PortalUnavailableError,
    SubjectAttendance,
)
from app.core.enums import AttendanceStatus


class FakeScenario(str, Enum):
    """Controlled scenarios supported by the FakePortalAdapter."""

    PYTHON_PRESENT = "python_present"
    PYTHON_ABSENT = "python_absent"
    PYTHON_UNKNOWN = "python_unknown"
    UNRELIABLE_ABSENT = "unreliable_absent"
    MIXED = "mixed"
    PORTAL_UNAVAILABLE = "portal_unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    AMBIGUOUS_RESPONSE = "ambiguous_response"


class FakePortalAdapter(BasePortalAdapter):
    """Simulated portal adapter operating strictly in-memory with zero network calls."""

    @property
    def adapter_name(self) -> str:
        return "fake"

    def __init__(
        self,
        scenario: FakeScenario | str = FakeScenario.PYTHON_ABSENT,
        is_config_valid: bool = True,
        is_auth_success: bool = True,
    ) -> None:
        self.scenario = self._parse_scenario(scenario)
        self.is_config_valid = is_config_valid
        self.is_auth_success = is_auth_success
        self.is_closed = False
        self._custom_subjects: Optional[List[SubjectAttendance]] = None

    @staticmethod
    def _parse_scenario(scenario: FakeScenario | str) -> FakeScenario:
        if isinstance(scenario, FakeScenario):
            return scenario
        normalized = scenario.strip().lower().replace("-", "_")
        aliases: dict[str, FakeScenario] = {
            "present": FakeScenario.PYTHON_PRESENT,
            "python_present": FakeScenario.PYTHON_PRESENT,
            "absent": FakeScenario.PYTHON_ABSENT,
            "python_absent": FakeScenario.PYTHON_ABSENT,
            "unknown": FakeScenario.PYTHON_UNKNOWN,
            "python_unknown": FakeScenario.PYTHON_UNKNOWN,
            "unreliable_absent": FakeScenario.UNRELIABLE_ABSENT,
            "mixed": FakeScenario.MIXED,
            "unavailable": FakeScenario.PORTAL_UNAVAILABLE,
            "portal_unavailable": FakeScenario.PORTAL_UNAVAILABLE,
            "malformed": FakeScenario.MALFORMED_RESPONSE,
            "malformed_response": FakeScenario.MALFORMED_RESPONSE,
            "ambiguous": FakeScenario.AMBIGUOUS_RESPONSE,
            "ambiguous_response": FakeScenario.AMBIGUOUS_RESPONSE,
        }
        if normalized in aliases:
            return aliases[normalized]
        raise ValueError(f"Unknown fake adapter scenario: {scenario}")

    def set_scenario(self, scenario: FakeScenario | str) -> None:
        """Switch scenario dynamically for tests."""
        self.scenario = self._parse_scenario(scenario)

    def set_custom_subjects(self, subjects: Optional[List[SubjectAttendance]]) -> None:
        """Override scenario outputs with custom subject attendance list."""
        self._custom_subjects = subjects

    def validate_config(self) -> bool:
        """Validate simulated configuration."""
        return self.is_config_valid

    def authenticate(self) -> bool:
        """Simulate authentication."""
        if not self.is_auth_success:
            raise PortalAuthenticationError("Simulated authentication failure: Invalid credentials.")
        return True

    def normalize_status(self, raw_status: Optional[str]) -> AttendanceStatus:
        """Normalize raw status strings to AttendanceStatus.

        Fails closed by returning UNKNOWN for any uncertain, empty, or ambiguous status.
        """
        if not raw_status:
            return AttendanceStatus.UNKNOWN

        clean = raw_status.strip().upper()
        if clean in {"PRESENT", "P", "ATTENDED", "YES"}:
            return AttendanceStatus.PRESENT
        elif clean in {"ABSENT", "A", "UNEXCUSED", "NO"}:
            return AttendanceStatus.ABSENT
        else:
            return AttendanceStatus.UNKNOWN

    def get_attendance_for_date(self, target_date: date) -> List[SubjectAttendance]:
        """Return simulated attendance records according to active scenario.

        Raises PortalUnavailableError or PortalParsingError if the scenario dictates.
        """
        if self._custom_subjects is not None:
            return self._custom_subjects

        if self.scenario == FakeScenario.PORTAL_UNAVAILABLE:
            raise PortalUnavailableError(
                "Simulated college portal outage: 503 Service Unavailable."
            )

        if self.scenario == FakeScenario.MALFORMED_RESPONSE:
            # Malformed data fails closed to UNKNOWN with reliability marked False
            return [
                SubjectAttendance(
                    subject_code="303PDS",
                    subject_name="Python for Data Science",
                    status=AttendanceStatus.UNKNOWN,
                    raw_status="<<UNPARSED HTML ERROR: <div>malformed</td>>>",
                    is_reliable=False,
                    metadata={"error": "Malformed response markup detected"},
                )
            ]

        if self.scenario == FakeScenario.AMBIGUOUS_RESPONSE:
            # Ambiguous statuses fail closed to UNKNOWN
            return [
                SubjectAttendance(
                    subject_code="303PDS",
                    subject_name="Python for Data Science",
                    status=self.normalize_status("TBD / EXEMPT?"),
                    raw_status="TBD / EXEMPT?",
                    is_reliable=False,
                    metadata={"note": "Ambiguous status detected"},
                )
            ]

        if self.scenario == FakeScenario.PYTHON_PRESENT:
            return [
                SubjectAttendance(
                    subject_code="303PDS",
                    subject_name="Python for Data Science",
                    status=AttendanceStatus.PRESENT,
                    raw_status="Present",
                    is_reliable=True,
                )
            ]

        if self.scenario == FakeScenario.PYTHON_ABSENT:
            return [
                SubjectAttendance(
                    subject_code="304VEP",
                    subject_name="Data Visualization using Excel and Powerbi",
                    status=AttendanceStatus.ABSENT,
                    raw_status="Absent",
                    is_reliable=True,
                )
            ]

        if self.scenario == FakeScenario.UNRELIABLE_ABSENT:
            return [
                SubjectAttendance(
                    subject_code="303PDS",
                    subject_name="Python for Data Science",
                    status=AttendanceStatus.ABSENT,
                    raw_status="Absent (Unconfirmed/Unverified Portal Flag)",
                    is_reliable=False,
                    metadata={"warning": "Unreliable attendance record flag detected"},
                )
            ]

        if self.scenario == FakeScenario.PYTHON_UNKNOWN:
            return [
                SubjectAttendance(
                    subject_code="303PDS",
                    subject_name="Python for Data Science",
                    status=AttendanceStatus.UNKNOWN,
                    raw_status="Pending Teacher Verification",
                    is_reliable=True,
                )
            ]

        if self.scenario == FakeScenario.MIXED:
            return [
                SubjectAttendance(
                    subject_code="303PDS",
                    subject_name="Python for Data Science",
                    status=AttendanceStatus.ABSENT,
                    raw_status="Absent",
                    is_reliable=True,
                ),
                SubjectAttendance(
                    subject_code="301ADS",
                    subject_name="Advance Data Structures and Algorithms",
                    status=AttendanceStatus.PRESENT,
                    raw_status="Present",
                    is_reliable=True,
                ),
                SubjectAttendance(
                    subject_code="302OPS",
                    subject_name="Operating System",
                    status=AttendanceStatus.UNKNOWN,
                    raw_status="Not Uploaded",
                    is_reliable=False,
                ),
            ]

        return []

    def close(self) -> None:
        """Simulate closing resources."""
        self.is_closed = True
