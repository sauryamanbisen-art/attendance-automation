"""Generic Playwright portal adapter implementing BasePortalAdapter.

Safety Invariants:
- Strictly READ-ONLY operations.
- Isolated browser context for all sessions.
- Credentials never logged or written to storage unredacted.
- Bypassing CAPTCHA, MFA, or rate limits is strictly PROHIBITED.
- Unknown, unexpected, or ambiguous status fails closed to UNKNOWN with is_reliable=False.
"""

import logging
from datetime import date
from typing import Any, List, Optional

from app.adapters.base.adapter import (
    BasePortalAdapter,
    PortalAuthenticationError,
    PortalConfigurationError,
    PortalParsingError,
    PortalUnavailableError,
    SubjectAttendance,
)
from app.adapters.playwright.browser_manager import PlaywrightBrowserManager
from app.adapters.playwright.config import PlaywrightPortalConfig, PortalSelectors
from app.adapters.playwright.discovery import PortalDiscoveryService
from app.adapters.playwright.normalizer import AttendanceNormalizer
from app.core.enums import AttendanceStatus
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)


class GenericPlaywrightPortalAdapter(BasePortalAdapter):
    """Generic Playwright portal adapter for automated, read-only attendance checking."""

    def __init__(
        self,
        config: Optional[PlaywrightPortalConfig] = None,
        browser_manager: Optional[PlaywrightBrowserManager] = None,
        discovery_service: Optional[PortalDiscoveryService] = None,
    ) -> None:
        self.config = config or PlaywrightPortalConfig()
        self.browser_manager = browser_manager or PlaywrightBrowserManager(
            headless=self.config.headless,
            timeout_ms=self.config.timeout_ms,
            browser_channel=self.config.browser_channel,
        )
        self.discovery_service = discovery_service or PortalDiscoveryService(
            selectors=self.config.selectors
        )
        self.normalizer = AttendanceNormalizer()
        self._is_authenticated = False

    @property
    def adapter_name(self) -> str:
        return "generic_playwright"

    @property
    def is_read_only(self) -> bool:
        return True

    def validate_config(self) -> bool:
        """Validate portal URL, auth parameters, and selector presence."""
        self.config.validate()
        return True

    def authenticate(self) -> bool:
        """Authenticate with the college portal or restore existing session.

        Safety:
        - If MFA or CAPTCHA is detected, raises PortalAuthenticationError.
        - Never attempts automated bypass.
        - Successful sessions are saved to local gitignored storage state.
        """
        self.validate_config()

        if self.config.is_placeholder_url():
            raise PortalConfigurationError(
                f"Cannot authenticate with placeholder URL '{self.config.portal_url}'. "
                "Please configure a valid college portal URL."
            )

        try:
            page = self.browser_manager.get_page(
                storage_state_path=self.config.storage_state_path
            )

            login_target = self.config.selectors.login_url or self.config.portal_url
            page.goto(login_target, wait_until=self.config.wait_until)

            # Check if existing session is already valid (not on login page)
            has_user_input = page.locator(self.config.selectors.username_input).count() > 0
            has_pass_input = page.locator(self.config.selectors.password_input).count() > 0

            if not has_user_input and not has_pass_input:
                logger.info("Existing browser session is still valid for %s", self.config.portal_url)
                self._is_authenticated = True
                return True

            # If MFA or CAPTCHA is present on login page, fail closed
            if page.locator(self.config.selectors.captcha_indicator).count() > 0:
                raise PortalAuthenticationError(
                    "Portal requires CAPTCHA verification. Automated bypass is strictly prohibited. "
                    "Please log in interactively to save a session state file."
                )

            if page.locator(self.config.selectors.mfa_indicator).count() > 0:
                raise PortalAuthenticationError(
                    "Portal requires interactive Multi-Factor Authentication (MFA). "
                    "Please log in interactively to save a session state file."
                )

            # Perform password authentication
            if not self.config.password:
                raise PortalAuthenticationError(
                    "Portal password is not configured. Set PORTAL_PASSWORD in your environment or Keychain."
                )

            page.fill(self.config.selectors.username_input, self.config.username or "")
            page.fill(self.config.selectors.password_input, self.config.password)
            page.click(self.config.selectors.submit_button)

            # Wait for response / navigation
            page.wait_for_load_state(self.config.wait_until)

            # Check for post-login MFA
            if page.locator(self.config.selectors.mfa_indicator).count() > 0:
                raise PortalAuthenticationError(
                    "Portal redirected to MFA verification. Automated bypass is strictly prohibited. "
                    "Please log in interactively in headed mode."
                )

            # Check for invalid credentials indicator or remaining on login
            still_has_login = page.locator(self.config.selectors.password_input).count() > 0
            if still_has_login:
                raise PortalAuthenticationError(
                    "Portal rejected login credentials or remained on authentication page."
                )

            # Save session state if configured
            if self.config.storage_state_path:
                self.browser_manager.save_storage_state(self.config.storage_state_path)

            self._is_authenticated = True
            logger.info("Successfully authenticated with portal at %s", self.config.portal_url)
            return True

        except (PortalAuthenticationError, PortalConfigurationError):
            raise
        except Exception as exc:
            safe_error = redact_string(str(exc))
            logger.error("Authentication failed: %s", safe_error)
            raise PortalUnavailableError(f"Could not reach or authenticate with portal: {safe_error}") from exc

    def get_attendance_for_date(self, target_date: date) -> List[SubjectAttendance]:
        """Navigate to portal attendance page and extract subject records for target date.

        Safety:
        - Fails closed to PortalUnavailableError on network errors.
        - Fails closed to UNKNOWN on ambiguous or missing rows.
        - Reliable ABSENT requires explicit portal affirmation.
        """
        self.validate_config()

        if self.config.is_placeholder_url():
            raise PortalUnavailableError(
                f"Portal URL '{self.config.portal_url}' is a placeholder. "
                "Configure a live college portal URL to run real checks."
            )

        page = self.browser_manager.get_page(
            storage_state_path=self.config.storage_state_path
        )

        # Navigate to attendance URL or click attendance nav link
        try:
            if self.config.selectors.attendance_url:
                page.goto(self.config.selectors.attendance_url, wait_until=self.config.wait_until)
            elif self.config.selectors.attendance_nav:
                nav_loc = page.locator(self.config.selectors.attendance_nav)
                if nav_loc.count() > 0:
                    nav_loc.first.click()
                    page.wait_for_load_state(self.config.wait_until)

            # Wait for attendance table
            table_loc = page.locator(self.config.selectors.attendance_table)
            if table_loc.count() == 0:
                logger.warning("Attendance table not found on page %s", page.url)
                return [
                    SubjectAttendance(
                        subject_code="UNKNOWN",
                        status=AttendanceStatus.UNKNOWN,
                        is_reliable=False,
                        raw_status=None,
                        metadata={"error": "Attendance table not found on page", "url": page.url},
                    )
                ]

            rows_loc = page.locator(self.config.selectors.table_rows)
            row_count = rows_loc.count()

            if row_count == 0:
                logger.warning("Attendance table found but contains 0 rows on %s", page.url)
                return []

            results: List[SubjectAttendance] = []
            for i in range(row_count):
                row = rows_loc.nth(i)
                cells = row.locator("td").all_inner_texts()
                if not cells:
                    continue

                subject_code = cells[0].strip() if len(cells) > 0 else "UNKNOWN"
                subject_name = cells[1].strip() if len(cells) > 1 else None
                raw_status = cells[-1].strip() if len(cells) > 0 else None

                status = self.normalize_status(raw_status)
                is_reliable = self.normalizer.determine_reliability(
                    status=status,
                    raw_status=raw_status,
                )

                results.append(
                    SubjectAttendance(
                        subject_code=subject_code,
                        subject_name=subject_name,
                        status=status,
                        is_reliable=is_reliable,
                        raw_status=raw_status,
                        metadata={"row_index": i},
                    )
                )

            return results

        except Exception as exc:
            safe_error = redact_string(str(exc))
            logger.error("Failed to extract attendance from portal: %s", safe_error)
            raise PortalUnavailableError(f"Failed to fetch attendance from portal: {safe_error}") from exc

    def normalize_status(self, raw_status: Optional[str]) -> AttendanceStatus:
        """Map raw portal status text to domain AttendanceStatus."""
        return self.normalizer.normalize_status(raw_status)

    def close(self) -> None:
        """Teardown browser context and resources."""
        self.browser_manager.close()
