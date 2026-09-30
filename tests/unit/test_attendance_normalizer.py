"""Unit tests for AttendanceNormalizer and reliability determination rules.

Strict Invariants Verified:
- UNKNOWN must NEVER become ABSENT.
- Missing, unrecognized, or ambiguous labels map to UNKNOWN.
- Reliable ABSENT requires explicit, clean evidence without ambiguity keywords.
- Ambiguous or provisional attendance has is_reliable=False.
"""

import pytest

from app.adapters.playwright.normalizer import AttendanceNormalizer
from app.core.enums import AttendanceStatus


class TestAttendanceNormalizer:
    @pytest.mark.parametrize(
        "raw_text",
        [
            "PRESENT",
            "Present",
            "present",
            "P",
            "p",
            "ATTENDED",
            "Attended",
            "YES",
            "yes",
            "PR",
            "PRES",
            "  Present  ",
            "Present.",
        ],
    )
    def test_normalize_present_tokens(self, raw_text: str):
        assert AttendanceNormalizer.normalize_status(raw_text) == AttendanceStatus.PRESENT

    @pytest.mark.parametrize(
        "raw_text",
        [
            "ABSENT",
            "Absent",
            "absent",
            "A",
            "a",
            "UNEXCUSED",
            "NO",
            "no",
            "AB",
            "  Absent  ",
            "Absent!",
        ],
    )
    def test_normalize_absent_tokens(self, raw_text: str):
        assert AttendanceNormalizer.normalize_status(raw_text) == AttendanceStatus.ABSENT

    @pytest.mark.parametrize(
        "raw_text",
        [
            "",
            "   ",
            None,
            "UNKNOWN",
            "Pending",
            "Duty Leave",
            "Medical Leave",
            "On Duty",
            "OD",
            "Exempt",
            "TBD",
            "N/A",
            "Not Marked",
            "Half Day",
            "1",
            "0",
            "<div>error</div>",
            "Unconfirmed Status",
        ],
    )
    def test_normalize_unknown_tokens_fail_closed(self, raw_text: str):
        """CRITICAL INVARIANT: Unknown, unexpected, or ambiguous status MUST return UNKNOWN."""
        assert AttendanceNormalizer.normalize_status(raw_text) == AttendanceStatus.UNKNOWN

    def test_unknown_never_becomes_absent(self):
        """CRITICAL SAFETY TEST: Verify that UNKNOWN is never mistakenly mapped to ABSENT."""
        ambiguous_cases = [
            "Pending Review",
            "Teacher not submitted",
            "Class Suspended",
            "Holiday",
            "Unspecified",
            "Error loading record",
        ]
        for case in ambiguous_cases:
            res = AttendanceNormalizer.normalize_status(case)
            assert res != AttendanceStatus.ABSENT
            assert res == AttendanceStatus.UNKNOWN


class TestReliabilityDetermination:
    def test_explicit_present_is_reliable(self):
        assert AttendanceNormalizer.determine_reliability(
            status=AttendanceStatus.PRESENT,
            raw_status="Present",
        ) is True

    def test_explicit_absent_is_reliable(self):
        assert AttendanceNormalizer.determine_reliability(
            status=AttendanceStatus.ABSENT,
            raw_status="Absent",
        ) is True

    def test_unreliable_absent_with_provisional_flag(self):
        """ABSENT with provisional, pending, or unverified keywords must have is_reliable=False."""
        unreliable_absents = [
            "Absent (Provisional)",
            "Absent - Pending Verification",
            "Absent (Disputed by student)",
            "Tentative Absent",
            "Absent (Unverified)",
        ]
        for raw in unreliable_absents:
            status = AttendanceNormalizer.normalize_status(raw)
            # Even if status were categorized as ABSENT or UNKNOWN, reliability must be False
            assert AttendanceNormalizer.determine_reliability(
                status=AttendanceStatus.ABSENT,
                raw_status=raw,
            ) is False

    def test_unknown_status_is_always_unreliable(self):
        """UNKNOWN status must ALWAYS have is_reliable=False."""
        assert AttendanceNormalizer.determine_reliability(
            status=AttendanceStatus.UNKNOWN,
            raw_status="Pending",
        ) is False

        assert AttendanceNormalizer.determine_reliability(
            status=AttendanceStatus.UNKNOWN,
            raw_status=None,
        ) is False

    def test_parsing_error_or_truncated_flag_forces_unreliable(self):
        """Metadata error flags immediately invalidate reliability."""
        assert AttendanceNormalizer.determine_reliability(
            status=AttendanceStatus.ABSENT,
            raw_status="Absent",
            metadata={"parsing_error": True},
        ) is False

        assert AttendanceNormalizer.determine_reliability(
            status=AttendanceStatus.ABSENT,
            raw_status="Absent",
            metadata={"truncated": True},
        ) is False
