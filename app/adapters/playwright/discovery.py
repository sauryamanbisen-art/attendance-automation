"""Read-only portal discovery and diagnostic service.

Safety Invariants:
- Strictly READ-ONLY: Never fills forms or submits actions on an unconfirmed portal.
- Inspects DOM for forms, inputs, MFA/CAPTCHA presence, and attendance tables.
- Helps contributors and users configure selectors safely without guessing.
- NEVER attempts to bypass CAPTCHA, MFA, or access controls.
"""

import logging
from typing import Any, Optional

from app.adapters.playwright.config import PortalSelectors

logger = logging.getLogger(__name__)


class PortalDiscoveryService:
    """Discovers and diagnoses portal page structures in a strictly read-only manner."""

    def __init__(self, selectors: Optional[PortalSelectors] = None) -> None:
        self.selectors = selectors or PortalSelectors()

    def inspect_page(self, page: Any, url: str) -> dict[str, Any]:
        """Navigate to portal URL and perform read-only structural discovery.

        Returns diagnostic report with discovered elements and safety flags.
        """
        logger.info("Performing read-only portal discovery at %s", url)
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            return {
                "url": url,
                "reachable": False,
                "error": str(exc),
                "is_login_page": False,
                "mfa_detected": False,
                "captcha_detected": False,
            }

        title = page.title()
        current_url = page.url

        # Check for login inputs
        has_user_input = False
        has_pass_input = False
        has_submit_btn = False

        try:
            has_user_input = page.locator(self.selectors.username_input).count() > 0
            has_pass_input = page.locator(self.selectors.password_input).count() > 0
            has_submit_btn = page.locator(self.selectors.submit_button).count() > 0
        except Exception:
            pass

        is_login_page = has_user_input and has_pass_input

        # Detect MFA or OTP indicators
        mfa_detected = False
        try:
            mfa_detected = page.locator(self.selectors.mfa_indicator).count() > 0
        except Exception:
            pass

        # Detect CAPTCHA or bot protection
        captcha_detected = False
        try:
            captcha_detected = page.locator(self.selectors.captcha_indicator).count() > 0
        except Exception:
            pass

        # Detect attendance table
        has_attendance_table = False
        table_rows_count = 0
        table_headers = []
        try:
            table_loc = page.locator(self.selectors.attendance_table)
            if table_loc.count() > 0:
                has_attendance_table = True
                table_rows_count = page.locator(self.selectors.table_rows).count()
                # Extract headers for mapping discovery
                headers = table_loc.first.locator("th").all_inner_texts()
                table_headers = [h.strip() for h in headers if h.strip()]
        except Exception:
            pass

        return {
            "url": current_url,
            "title": title,
            "reachable": True,
            "is_login_page": is_login_page,
            "has_user_input": has_user_input,
            "has_pass_input": has_pass_input,
            "has_submit_button": has_submit_btn,
            "mfa_detected": mfa_detected,
            "captcha_detected": captcha_detected,
            "has_attendance_table": has_attendance_table,
            "table_headers": table_headers,
            "table_rows_count": table_rows_count,
            "requires_interactive_auth": mfa_detected or captcha_detected,
        }
