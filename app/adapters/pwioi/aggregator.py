"""Multiple-period attendance aggregation for PWIOI portal.

PWIOI Daily Records may list multiple periods for the same course on the same date:
e.g.
  2026-08-04-period 1 -> PRESENT
  2026-08-04-period 2 -> PRESENT
or:
  2026-08-03-period 1 -> ABSENT

Aggregation Safety Rules:
1. If no periods found for date: status=UNKNOWN, is_reliable=False.
2. If any period is ambiguous, UNKNOWN, or has is_reliable=False: status=UNKNOWN, is_reliable=False.
3. If all periods are reliably PRESENT: status=PRESENT, is_reliable=True.
4. If any period is reliably ABSENT (and no periods are ambiguous): status=ABSENT, is_reliable=True.
5. All period breakdowns are preserved in SubjectAttendance.metadata["periods"].
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, List, Optional

from app.adapters.base.adapter import SubjectAttendance
from app.core.enums import AttendanceStatus


@dataclass(frozen=True)
class PWIOIPeriodRecord:
    """Individual period record from PWIOI Daily Records."""

    period: str
    target_date: date
    raw_status: str
    status: AttendanceStatus
    is_reliable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "date": self.target_date.isoformat(),
            "raw_status": self.raw_status,
            "status": self.status.value,
            "is_reliable": self.is_reliable,
        }


class PWIOIPeriodAggregator:
    """Pure, deterministic aggregator for multiple periods of a course on a date."""

    @staticmethod
    def is_stale_or_pending(period_records: List[PWIOIPeriodRecord]) -> bool:
        """Return True if records are missing, marked NOT MARKED / UNMARKED, or unverified."""
        if not period_records:
            return True
        for p in period_records:
            raw = (p.raw_status or "").upper()
            if "NOT MARKED" in raw or "UNMARKED" in raw or "PENDING" in raw:
                return True
            if p.status == AttendanceStatus.UNKNOWN or not p.is_reliable:
                return True
        return False

    @staticmethod
    def aggregate(
        course_code: str,
        course_name: Optional[str],
        target_date: date,
        period_records: List[PWIOIPeriodRecord],
        retries_attempted: int = 0,
    ) -> SubjectAttendance:
        """Aggregate period records into a single SubjectAttendance record.

        Safety:
        - Never converts ambiguous or partial data into reliable ABSENT.
        - Fails closed to UNKNOWN on missing or disputed periods.
        - Records retry audit metadata.
        """
        base_meta: dict[str, Any] = {
            "date": target_date.isoformat(),
            "retries_attempted": retries_attempted,
        }
        if retries_attempted > 0:
            base_meta["refreshed"] = True

        # 1. No periods found for this course on target date
        if not period_records:
            return SubjectAttendance(
                subject_code=course_code,
                subject_name=course_name,
                status=AttendanceStatus.UNKNOWN,
                is_reliable=False,
                raw_status=None,
                metadata={
                    **base_meta,
                    "reason": "No attendance records found for target date",
                    "periods": [],
                },
            )

        # 2. Check for any unreliable or UNKNOWN periods (e.g. NOT MARKED)
        has_unreliable = any(not p.is_reliable for p in period_records)
        has_unknown = any(p.status == AttendanceStatus.UNKNOWN for p in period_records)

        if has_unreliable or has_unknown:
            raw_summary = "; ".join(f"{p.period}: {p.raw_status}" for p in period_records)
            return SubjectAttendance(
                subject_code=course_code,
                subject_name=course_name,
                status=AttendanceStatus.UNKNOWN,
                is_reliable=False,
                raw_status=raw_summary,
                metadata={
                    **base_meta,
                    "reason": "One or more periods have ambiguous or unreliable attendance status",
                    "periods": [p.to_dict() for p in period_records],
                },
            )

        # 3. Check for any reliably ABSENT periods
        absent_periods = [p for p in period_records if p.status == AttendanceStatus.ABSENT]
        if absent_periods:
            raw_summary = "; ".join(f"{p.period}: {p.raw_status}" for p in period_records)
            return SubjectAttendance(
                subject_code=course_code,
                subject_name=course_name,
                status=AttendanceStatus.ABSENT,
                is_reliable=True,
                raw_status=raw_summary,
                metadata={
                    **base_meta,
                    "periods": [p.to_dict() for p in period_records],
                    "absent_periods": [p.period for p in absent_periods],
                },
            )

        # 4. Check if all periods are PRESENT
        all_present = all(p.status == AttendanceStatus.PRESENT for p in period_records)
        if all_present:
            raw_summary = "; ".join(f"{p.period}: {p.raw_status}" for p in period_records)
            return SubjectAttendance(
                subject_code=course_code,
                subject_name=course_name,
                status=AttendanceStatus.PRESENT,
                is_reliable=True,
                raw_status=raw_summary,
                metadata={
                    **base_meta,
                    "periods": [p.to_dict() for p in period_records],
                },
            )

        # 5. Fallback fail-closed
        raw_summary = "; ".join(f"{p.period}: {p.raw_status}" for p in period_records)
        return SubjectAttendance(
            subject_code=course_code,
            subject_name=course_name,
            status=AttendanceStatus.UNKNOWN,
            is_reliable=False,
            raw_status=raw_summary,
            metadata={
                **base_meta,
                "reason": "Unexpected attendance period combination",
                "periods": [p.to_dict() for p in period_records],
            },
        )
