"""Configuration and selector definitions for PWIOI Student Portal adapter.

Portal: https://app.pwioi.club
Login URL: https://app.pwioi.club/auth/student/login
Attendance URL: https://app.pwioi.club/dashboard/student/attendance

Safety Invariants:
- Strictly READ-ONLY operations.
- Zero hardcoded credentials or tokens.
- Google Sign-In is manual only; no automated bypass or credential injection.
- Restrictive storage state file permissions (0600) and gitignored.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from app.adapters.base.adapter import PortalConfigurationError


@dataclass
class PWIOISelectors:
    """CSS and semantic text selectors for PWIOI student portal navigation."""

    # Login page
    login_url: str = "https://app.pwioi.club/auth/student/login"
    login_title: str = "Student Login"
    google_signin_button: str = "button:has-text('Sign in with Google'), :has-text('Sign in with Google')"
    login_subheading: str = ":has-text('Sign in to access your dashboard')"

    # Attendance Dashboard
    attendance_url: str = "https://app.pwioi.club/dashboard/student/attendance"
    dashboard_indicator: str = ":has-text('Overall Attendance'), :has-text('Enrolled Courses'), :has-text('Course Breakdown')"
    academic_term_dropdown: str = "select, select[name*='term'], [role='combobox']:has-text('Term'), button:has-text('Term')"
    academic_term_container: str = "div:has-text('Academic Term'), [aria-label*='Term']"

    # Course Breakdown
    course_breakdown_section: str = ":has-text('Course Breakdown')"
    course_card: str = ".grid > div.cursor-pointer, div.cursor-pointer:has(h4), .grid > div:has(h4), div.group:has(h4), div:has(p:has-text('Click to view details'))"
    view_details_action: str = "p:has-text('Click to view details'), button:has-text('Click to view details'), a:has-text('Click to view details'), button:has-text('details'), a:has-text('details'), [role='button']:has-text('details')"
    loading_skeleton: str = ".animate-pulse"

    # Course Detail Modal & Daily Records
    course_detail_indicator: str = ":has-text('Monthly Overview'), :has-text('Daily Records')"
    modal_container: str = ".fixed.inset-0, div[role='dialog']"
    modal_close_button: str = ".fixed.inset-0 .bg-\\[\\#12294c\\] button, .fixed.inset-0 button:has(svg), div[role='dialog'] button:has(svg), button:has-text('Back'), a:has-text('Back'), button[aria-label*='back' i], button[aria-label*='close' i]"
    daily_records_tab: str = "button:has-text('Daily Records'), a:has-text('Daily Records'), [role='tab']:has-text('Daily Records')"
    daily_records_section: str = ":has-text('Daily Records')"
    search_date_input: str = "input[placeholder*='date' i], input[placeholder='Search by date...'], input[type='search'], input[placeholder*='Search' i]"
    record_row: str = "div.bg-white.rounded-sm.border:has(p.font-semibold), div.rounded-sm.border:has(p.font-semibold), .space-y-3 > div.bg-white:has(p.font-semibold), div[role='dialog'] .space-y-3 > div.bg-white, .fixed.inset-0 .space-y-3 > div.bg-white, .fixed.inset-0 .space-y-3 > div, div[role='dialog'] .space-y-3 > div, table tbody tr"
    no_records_indicator: str = ":has-text('No Records Found'), :has-text('No attendance records match')"
    back_button: str = "button:has-text('Back'), a:has-text('Back'), button[aria-label*='back' i], .fixed.inset-0 button:has(svg)"


@dataclass
class PWIOIPortalConfig:
    """Runtime configuration for PWIOI Portal Adapter."""

    portal_url: str = "https://app.pwioi.club/auth/student/login"
    attendance_url: str = "https://app.pwioi.club/dashboard/student/attendance"
    academic_term: Optional[str] = None  # e.g. "3" or "Term 3". If None, active term is verified/detected.
    storage_state_path: str = "storage_state/pwioi_session.json"
    headless: bool = True
    timeout_ms: int = 15000
    browser_channel: Optional[str] = None
    manual_login_timeout_ms: int = 300000
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    enable_refresh_on_stale: bool = True
    wait_until: str = "domcontentloaded"
    selectors: PWIOISelectors = field(default_factory=PWIOISelectors)

    def validate(self) -> bool:
        """Validate URL endpoints and configurations.

        Raises:
            PortalConfigurationError: If URLs are invalid or placeholder.
        """
        for url_name, url_val in [
            ("portal_url", self.portal_url),
            ("attendance_url", self.attendance_url),
        ]:
            if not url_val or not url_val.strip():
                raise PortalConfigurationError(f"{url_name} must be configured.")
            parsed = urlparse(url_val.strip())
            if not parsed.scheme or not parsed.netloc:
                raise PortalConfigurationError(f"Invalid {url_name}: '{url_val}'.")
            if "example.com" in url_val or "portal.example.edu" in url_val:
                raise PortalConfigurationError(
                    f"Cannot use placeholder URL '{url_val}' for PWIOI adapter."
                )

        return True

    def safe_dict(self) -> dict[str, Any]:
        """Safe representation without sensitive internal paths."""
        return {
            "portal_url": self.portal_url,
            "attendance_url": self.attendance_url,
            "academic_term": self.academic_term,
            "storage_state_path": self.storage_state_path,
            "headless": self.headless,
            "timeout_ms": self.timeout_ms,
            "browser_channel": self.browser_channel,
            "manual_login_timeout_ms": self.manual_login_timeout_ms,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
        }
