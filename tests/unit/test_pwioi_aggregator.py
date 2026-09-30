"""Unit tests for PWIOIPeriodAggregator and multiple-period attendance safety."""

from datetime import date
import pytest

from app.adapters.base.adapter import SubjectAttendance
from app.adapters.pwioi.aggregator import PWIOIPeriodAggregator, PWIOIPeriodRecord
from app.core.enums import AttendanceStatus


class TestPWIOIPeriodAggregator:
    """Validate multiple-period aggregation and fail-closed safety."""

    TARGET_DATE = date(2026, 8, 4)

    def test_no_periods_returns_unknown_unreliable(self):
        """When no records exist for a course on the target date, fail closed to UNKNOWN."""
        res = PWIOIPeriodAggregator.aggregate(
            course_code="302OPS",
            course_name="Operating System",
            target_date=self.TARGET_DATE,
            period_records=[],
        )
        assert res.subject_code == "302OPS"
        assert res.subject_name == "Operating System"
        assert res.status == AttendanceStatus.UNKNOWN
        assert res.is_reliable is False
        assert "No attendance records found" in res.metadata["reason"]

    def test_single_period_present(self):
        """Single period PRESENT evaluates to PRESENT with is_reliable=True."""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="PRESENT",
                status=AttendanceStatus.PRESENT,
                is_reliable=True,
            )
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.PRESENT
        assert res.is_reliable is True
        assert len(res.metadata["periods"]) == 1

    def test_single_period_absent(self):
        """Single period ABSENT evaluates to ABSENT with is_reliable=True."""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="ABSENT",
                status=AttendanceStatus.ABSENT,
                is_reliable=True,
            )
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.ABSENT
        assert res.is_reliable is True
        assert "absent_periods" in res.metadata
        assert res.metadata["absent_periods"] == ["period 1"]

    def test_single_period_unknown_fails_closed(self):
        """Single period UNKNOWN evaluates to UNKNOWN with is_reliable=False."""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="DUTY_LEAVE",
                status=AttendanceStatus.UNKNOWN,
                is_reliable=False,
            )
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.UNKNOWN
        assert res.is_reliable is False

    def test_multiple_periods_all_present(self):
        """Multiple periods all marked PRESENT evaluate to PRESENT, is_reliable=True."""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="PRESENT",
                status=AttendanceStatus.PRESENT,
                is_reliable=True,
            ),
            PWIOIPeriodRecord(
                period="period 2",
                target_date=self.TARGET_DATE,
                raw_status="PRESENT",
                status=AttendanceStatus.PRESENT,
                is_reliable=True,
            ),
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.PRESENT
        assert res.is_reliable is True
        assert len(res.metadata["periods"]) == 2

    def test_multiple_periods_mixed_present_and_absent(self):
        """If one period is PRESENT and one is ABSENT, discrepancy exists: ABSENT, reliable=True."""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="PRESENT",
                status=AttendanceStatus.PRESENT,
                is_reliable=True,
            ),
            PWIOIPeriodRecord(
                period="period 2",
                target_date=self.TARGET_DATE,
                raw_status="ABSENT",
                status=AttendanceStatus.ABSENT,
                is_reliable=True,
            ),
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.ABSENT
        assert res.is_reliable is True
        assert res.metadata["absent_periods"] == ["period 2"]

    def test_multiple_periods_all_absent(self):
        """If all periods are ABSENT, evaluates to ABSENT, reliable=True."""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="ABSENT",
                status=AttendanceStatus.ABSENT,
                is_reliable=True,
            ),
            PWIOIPeriodRecord(
                period="period 2",
                target_date=self.TARGET_DATE,
                raw_status="ABSENT",
                status=AttendanceStatus.ABSENT,
                is_reliable=True,
            ),
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.ABSENT
        assert res.is_reliable is True
        assert res.metadata["absent_periods"] == ["period 1", "period 2"]

    def test_multiple_periods_partial_or_ambiguous_fails_closed(self):
        """CRITICAL SAFETY: If one period is ABSENT but another is UNKNOWN/provisional, fail closed!"""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="ABSENT",
                status=AttendanceStatus.ABSENT,
                is_reliable=True,
            ),
            PWIOIPeriodRecord(
                period="period 2",
                target_date=self.TARGET_DATE,
                raw_status="Pending Review",
                status=AttendanceStatus.UNKNOWN,
                is_reliable=False,
            ),
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.UNKNOWN
        assert res.is_reliable is False
        assert "ambiguous or unreliable" in res.metadata["reason"].lower()

    def test_multiple_periods_present_and_unreliable_fails_closed(self):
        """If one period is PRESENT and another is unreliable, fail closed to UNKNOWN."""
        records = [
            PWIOIPeriodRecord(
                period="period 1",
                target_date=self.TARGET_DATE,
                raw_status="PRESENT",
                status=AttendanceStatus.PRESENT,
                is_reliable=True,
            ),
            PWIOIPeriodRecord(
                period="period 2",
                target_date=self.TARGET_DATE,
                raw_status="TBD",
                status=AttendanceStatus.UNKNOWN,
                is_reliable=False,
            ),
        ]
        res = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, records)
        assert res.status == AttendanceStatus.UNKNOWN
        assert res.is_reliable is False
