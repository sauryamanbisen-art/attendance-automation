"""Attendance status normalization and reliability determination.

Safety Invariants:
- UNKNOWN must NEVER become ABSENT.
- Unexpected, ambiguous, or empty labels fail closed to UNKNOWN with is_reliable=False.
- Reliable ABSENT requires explicit, unambiguous evidence.
"""

import re
from typing import Any, Optional

from app.core.enums import AttendanceStatus

# Explicit tokens for PRESENT
PRESENT_TOKENS = {
    "PRESENT",
    "P",
    "ATTENDED",
    "YES",
    "PR",
    "PRES",
}

# Explicit tokens for ABSENT
ABSENT_TOKENS = {
    "ABSENT",
    "A",
    "UNEXCUSED",
    "NO",
    "AB",
}

# Unreliable indicators (provisional, pending, disputed, medical, leave, unverified, or not marked)
UNRELIABLE_PATTERN = re.compile(
    r"(pending|provisional|unverified|dispute|tentative|tbd|unknown|leave|duty|od|medical|exempt|n/?a|not\s*marked|unmarked)",
    re.IGNORECASE,
)


class AttendanceNormalizer:
    """Normalizes raw portal attendance text into domain AttendanceStatus with reliability scoring."""

    @staticmethod
    def normalize_status(raw_status: Optional[str]) -> AttendanceStatus:
        """Map raw portal status text to domain AttendanceStatus.

        Guarantees:
        - None or empty string -> UNKNOWN
        - Exact present tokens -> PRESENT
        - Exact absent tokens -> ABSENT
        - Any unrecognized, mixed, or ambiguous text -> UNKNOWN
        """
        if not raw_status:
            return AttendanceStatus.UNKNOWN

        clean = raw_status.strip().upper()

        # Remove surrounding punctuation / extra whitespace
        clean = re.sub(r"[^\w\s-]", "", clean).strip()

        if clean in PRESENT_TOKENS:
            return AttendanceStatus.PRESENT

        if clean in ABSENT_TOKENS:
            return AttendanceStatus.ABSENT

        # Fail closed on anything else
        return AttendanceStatus.UNKNOWN

    @staticmethod
    def determine_reliability(
        status: AttendanceStatus,
        raw_status: Optional[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Determine whether the attendance record is sufficiently reliable for decision making.

        Safety Requirements:
        - UNKNOWN is ALWAYS unreliable (is_reliable=False).
        - Any text containing provisional/unverified/pending flags is unreliable.
        - Truncated or incomplete data is unreliable.
        - PRESENT is reliable only when explicitly verified.
        - ABSENT is reliable ONLY when explicitly affirmed by portal without ambiguity flags.
        """
        meta = metadata or {}

        # 1. Flagged as parsing error or partial page load
        if meta.get("parsing_error") or meta.get("truncated"):
            return False

        # 2. Status UNKNOWN is never reliable
        if status == AttendanceStatus.UNKNOWN:
            return False

        if not raw_status:
            return False

        # 3. Text contains unverified / provisional / disputed keywords
        if UNRELIABLE_PATTERN.search(raw_status):
            return False

        # 4. Explicit verification for ABSENT: must be a known clean absent token
        clean = raw_status.strip().upper()
        clean = re.sub(r"[^\w\s-]", "", clean).strip()

        if status == AttendanceStatus.ABSENT:
            return clean in ABSENT_TOKENS

        if status == AttendanceStatus.PRESENT:
            return clean in PRESENT_TOKENS

        return False
