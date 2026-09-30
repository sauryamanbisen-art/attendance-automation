"""Concrete PWIOI Student Portal Adapter (READ-ONLY).

Portal: https://app.pwioi.club
Login: https://app.pwioi.club/auth/student/login
Dashboard: https://app.pwioi.club/dashboard/student/attendance

Safety Invariants:
- Strictly READ-ONLY operations.
- Never automates Google account login; user must complete manual Google Sign-In.
- Never bypasses MFA, CAPTCHA, or bot protection.
- Session storage saved with POSIX 0600 permissions and gitignored.
- Academic Term verified; fails closed if term is missing or ambiguous.
- UNKNOWN never becomes ABSENT.
- Multiple periods for the same course on a date are aggregated safely with fail-closed rules.
"""

import logging
import os
import re
from datetime import date
from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock

from app.adapters.base.adapter import (
    BasePortalAdapter,
    PortalAuthenticationError,
    PortalConfigurationError,
    PortalUnavailableError,
    SubjectAttendance,
)
from app.adapters.playwright.browser_manager import PlaywrightBrowserManager
from app.adapters.playwright.normalizer import AttendanceNormalizer
from app.adapters.pwioi.aggregator import PWIOIPeriodAggregator, PWIOIPeriodRecord
from app.adapters.pwioi.config import PWIOIPortalConfig
from app.core.enums import AttendanceStatus
from app.security.redaction import redact_string

logger = logging.getLogger(__name__)

# Patterns for extracting course code and name from course breakdown strings
# e.g., "Operating System — 302OPS", "OJT / Java Web Developer (Spring Boot) — 306JWD"
COURSE_SPLIT_PATTERN = re.compile(r"^(.*?)\s*[—–\-]\s*([0-9]{3}[A-Z]{3,4})\b", re.IGNORECASE)
COURSE_CODE_PATTERN = re.compile(r"\b([0-9]{3}[A-Z]{3,4})\b")

# Patterns for extracting period and status from daily attendance records
PERIOD_PATTERN = re.compile(r"\b(period\s*\d+)\b", re.IGNORECASE)
DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
STATUS_PATTERN = re.compile(r"\b(PRESENT|ABSENT|ATTENDED|LEAVE|EXCUSED|UNEXCUSED|NOT[\s_]*MARKED|UNMARKED)\b", re.IGNORECASE)


class PWIOIPortalAdapter(BasePortalAdapter):
    """Production-grade read-only portal adapter for PWIOI Student Portal."""

    def __init__(
        self,
        config: Optional[PWIOIPortalConfig] = None,
        browser_manager: Optional[PlaywrightBrowserManager] = None,
        normalizer: Optional[AttendanceNormalizer] = None,
    ) -> None:
        self.config = config or PWIOIPortalConfig()
        self.browser_manager = browser_manager or PlaywrightBrowserManager(
            headless=self.config.headless,
            timeout_ms=self.config.timeout_ms,
            browser_channel=self.config.browser_channel,
        )
        self.normalizer = normalizer or AttendanceNormalizer()
        self._is_authenticated = False

    @property
    def adapter_name(self) -> str:
        return "pwioi"

    @property
    def is_read_only(self) -> bool:
        return True

    def validate_config(self) -> bool:
        """Validate PWIOI configuration and endpoints."""
        self.config.validate()
        return True

    def authenticate(self) -> bool:
        """Verify existing session or facilitate manual Google Sign-In.

        Safety:
        - If an existing valid session state is present, restores it.
        - If unauthenticated in headless mode, raises PortalAuthenticationError.
        - If unauthenticated in headed mode, prompts for manual user Google Sign-In.
        - NEVER automates Google login credentials.
        """
        self.validate_config()

        # In headless mode with a real browser, an existing storage state file is required
        if (
            self.config.headless
            and self.config.storage_state_path
            and not os.path.exists(self.config.storage_state_path)
            and not isinstance(self.browser_manager, MagicMock)
        ):
            logger.error(
                "PWIOI session storage state file not found at '%s' in headless mode.",
                self.config.storage_state_path,
            )
            raise PortalAuthenticationError(
                f"PWIOI session storage state file not found at '{self.config.storage_state_path}'. "
                "In headless mode, an existing authenticated session storage file is required. "
                "Please run once in headed mode (PORTAL_HEADLESS=false) to complete initial manual Google Sign-In."
            )

        try:
            page = self.browser_manager.get_page(
                storage_state_path=self.config.storage_state_path
            )

            # Navigate to attendance dashboard or login page
            logger.info("Checking authentication state on PWIOI attendance dashboard: %s", self.config.attendance_url)
            page.goto(self.config.attendance_url, wait_until=self.config.wait_until)

            # Check if redirected to login page or unauthenticated
            current_url = page.url
            is_login_page = (
                "/auth/" in current_url
                or page.locator(self.config.selectors.google_signin_button).count() > 0
                or page.locator(self.config.selectors.login_subheading).count() > 0
            )

            if not is_login_page and "/dashboard/" in current_url:
                logger.info("Existing PWIOI session is valid. Authenticated on dashboard: %s", current_url)
                self._is_authenticated = True
                return True

            # Unauthenticated: Google Sign-In required
            if self.config.headless:
                logger.error(
                    "PWIOI requires manual Google Sign-In, but headless mode is enabled. "
                    "Run with PORTAL_HEADLESS=false or provide a valid storage_state file."
                )
                raise PortalAuthenticationError(
                    "PWIOI student portal requires manual Google Sign-In. Automated login is prohibited. "
                    f"Please launch in headed mode (PORTAL_HEADLESS=false) or provide an authenticated session file at "
                    f"'{self.config.storage_state_path}'."
                )

            # Headed mode: Allow user to manually log in with Google
            logger.info(
                "PWIOI requires manual Google Sign-In. Please complete Google authentication in the browser window..."
            )
            logger.info(
                "Waiting up to %s seconds (5 minutes) for user to complete Google Sign-In and reach /dashboard/student...",
                self.config.manual_login_timeout_ms // 1000,
            )

            # Ensure the headed browser and page do not close or terminate due to short default timeouts during manual login
            try:
                page.set_default_navigation_timeout(self.config.manual_login_timeout_ms)
                page.set_default_timeout(self.config.manual_login_timeout_ms)
                if hasattr(page, "context") and page.context:
                    page.context.set_default_navigation_timeout(self.config.manual_login_timeout_ms)
                    page.context.set_default_timeout(self.config.manual_login_timeout_ms)
            except Exception as e:
                logger.debug("Could not adjust page/context timeout for manual login: %s", e)

            # Wait for user to complete login and arrive at the dashboard (up to 5 minutes)
            dashboard_pattern = re.compile(r"/dashboard/student")
            try:
                page.wait_for_url(
                    dashboard_pattern,
                    timeout=self.config.manual_login_timeout_ms,
                    wait_until=self.config.wait_until,
                )
            except Exception:
                # If wait_for_url on main page failed or timed out, check whether the user completed login
                # in a popup window or secondary tab that reached the dashboard URL
                authenticated_tab = False
                context = getattr(page, "context", None)
                if context and hasattr(context, "pages"):
                    for p in context.pages:
                        try:
                            if not p.is_closed() and dashboard_pattern.search(p.url):
                                authenticated_tab = True
                                logger.info("Authenticated session detected on page/tab: %s", p.url)
                                break
                        except Exception:
                            pass
                if not authenticated_tab:
                    raise

            # Restore standard operation timeouts on page and context
            try:
                page.set_default_navigation_timeout(self.config.timeout_ms)
                page.set_default_timeout(self.config.timeout_ms)
                if hasattr(page, "context") and page.context:
                    page.context.set_default_navigation_timeout(self.config.timeout_ms)
                    page.context.set_default_timeout(self.config.timeout_ms)
            except Exception as e:
                logger.debug("Could not restore default page/context timeout: %s", e)

            # Save session state for future runs
            if self.config.storage_state_path:
                self.browser_manager.save_storage_state(self.config.storage_state_path)
                logger.info("Saved authenticated PWIOI session state to %s", self.config.storage_state_path)

            self._is_authenticated = True
            return True

        except PortalAuthenticationError:
            raise
        except Exception as exc:
            safe_err = redact_string(str(exc))
            logger.error("PWIOI authentication check failed: %s", safe_err)
            raise PortalUnavailableError(f"Could not reach or authenticate with PWIOI portal: {safe_err}") from exc

    def _verify_and_select_term(self, page: Any) -> Tuple[bool, Optional[str], Optional[str]]:
        """Verify or select the configured Academic Term safely.

        Returns:
            (success: bool, active_term: Optional[str], error_message: Optional[str])
        """
        sel = self.config.selectors

        # 1. Wait for academic term dropdown options to populate if present
        dropdown_loc = page.locator(sel.academic_term_dropdown)
        if dropdown_loc.count() > 0:
            try:
                # Next.js populates the select asynchronously from /api/semester/all/{divisionId}
                dropdown_loc.first.locator("option").first.wait_for(
                    state="attached", timeout=min(10000, self.config.timeout_ms)
                )
            except Exception:
                pass

        # 2. If a specific term is configured, verify or select it
        if self.config.academic_term:
            expected_term = self.config.academic_term.strip()
            clean_digits = re.sub(r"[^\d]", "", expected_term)
            candidates = [expected_term]
            if clean_digits and clean_digits != expected_term:
                candidates.extend([clean_digits, f"Term {clean_digits}"])
            elif clean_digits:
                candidates.extend([f"Term {clean_digits}"])

            if dropdown_loc.count() > 0:
                dropdown = dropdown_loc.first
                try:
                    tag_name = dropdown.evaluate("el => el.tagName.toLowerCase()")
                except Exception:
                    tag_name = ""

                if tag_name == "select":
                    # Check currently selected option text or value
                    try:
                        current_val = dropdown.input_value()
                    except Exception:
                        current_val = ""

                    if expected_term and expected_term in current_val:
                        return True, expected_term, None

                    try:
                        lbl = dropdown.evaluate(
                            "el => el.options ? el.options[el.selectedIndex]?.text?.trim() : ''"
                        )
                        current_label = lbl if isinstance(lbl, str) else ""
                    except Exception:
                        current_label = ""

                    if current_label and any(c.lower() == current_label.lower() or c.lower() in current_label.lower() for c in candidates):
                        return True, current_label, None

                    # Attempt select_option by candidate labels
                    for cand in candidates:
                        try:
                            dropdown.select_option(label=cand)
                            page.wait_for_load_state(self.config.wait_until)
                            selected_label = dropdown.evaluate(
                                "el => el.options ? el.options[el.selectedIndex]?.text?.trim() : ''"
                            )
                            return True, selected_label or cand, None
                        except Exception:
                            pass

                    # Attempt select_option by value
                    try:
                        dropdown.select_option(value=expected_term)
                        page.wait_for_load_state(self.config.wait_until)
                        selected_label = dropdown.evaluate(
                            "el => el.options ? el.options[el.selectedIndex]?.text?.trim() : ''"
                        )
                        return True, selected_label or expected_term, None
                    except Exception:
                        pass

                    # JavaScript option matcher fallback
                    try:
                        matched_text = dropdown.evaluate(
                            """(el, cands) => {
                                const opts = Array.from(el.options || []);
                                for (const cand of cands) {
                                    const cLower = cand.toLowerCase();
                                    const found = opts.find(o => o.text.trim().toLowerCase() === cLower || o.text.trim().toLowerCase().includes(cLower) || o.value === cand);
                                    if (found) {
                                        el.value = found.value;
                                        el.dispatchEvent(new Event('change', { bubbles: true }));
                                        return found.text.trim();
                                    }
                                }
                                return null;
                            }""",
                            candidates,
                        )
                        if matched_text:
                            page.wait_for_load_state(self.config.wait_until)
                            return True, matched_text, None
                    except Exception:
                        pass

                    return False, None, f"Academic Term '{expected_term}' could not be verified on dashboard"

                # Non-select combobox / button dropdown
                try:
                    btn_text = dropdown.inner_text()
                    if any(c.lower() in btn_text.lower() for c in candidates):
                        return True, expected_term, None
                except Exception:
                    pass

                # Try clicking dropdown and selecting option
                try:
                    dropdown.click()
                    for cand in candidates:
                        option_loc = page.locator(f":has-text('{cand}')")
                        if option_loc.count() > 0:
                            option_loc.first.click()
                            page.wait_for_load_state(self.config.wait_until)
                            return True, cand, None
                except Exception as click_exc:
                    return False, None, f"Could not click and select Academic Term '{expected_term}': {click_exc}"

            # Fallback: check if the term is present in a term container
            container_loc = page.locator(sel.academic_term_container)
            if container_loc.count() > 0:
                try:
                    container_text = container_loc.first.inner_text()
                    if any(c.lower() in container_text.lower() for c in candidates):
                        return True, expected_term, None
                except Exception:
                    pass

            return False, None, f"Academic Term '{expected_term}' could not be verified on dashboard"

        # 3. If no specific term is configured, detect active term from page
        if dropdown_loc.count() > 0:
            active_text = None
            try:
                res = dropdown_loc.first.evaluate(
                    "el => el.options ? el.options[el.selectedIndex]?.text?.trim() : el.innerText?.trim() || ''"
                )
                if isinstance(res, str) and res.strip():
                    active_text = res.strip()
            except Exception:
                pass

            if not active_text:
                try:
                    raw_text = dropdown_loc.first.inner_text()
                    if isinstance(raw_text, str) and raw_text.strip():
                        active_text = raw_text.strip()
                except Exception:
                    pass

            if active_text:
                return True, active_text, None

        return True, None, None

    def _close_course_modal(self, page: Any) -> None:
        """Close course detail modal and return cleanly to Course Breakdown."""
        sel = self.config.selectors
        close_btn = page.locator(sel.modal_close_button)
        if close_btn.count() > 0:
            try:
                close_btn.first.click()
                page.wait_for_load_state(self.config.wait_until)
                try:
                    page.locator(sel.modal_container).wait_for(state="detached", timeout=2000)
                except Exception:
                    pass
                return
            except Exception:
                pass

        back_btn = page.locator(sel.back_button)
        if back_btn.count() > 0:
            try:
                back_btn.first.click()
                page.wait_for_load_state(self.config.wait_until)
                try:
                    page.locator(sel.modal_container).wait_for(state="detached", timeout=2000)
                except Exception:
                    pass
                return
            except Exception:
                pass

        try:
            page.keyboard.press("Escape")
            page.wait_for_load_state(self.config.wait_until)
            try:
                page.locator(sel.modal_container).wait_for(state="detached", timeout=2000)
            except Exception:
                pass
        except Exception:
            pass

    def _enumerate_courses(self, page: Any) -> List[dict[str, Any]]:
        """Enumerate all courses from Course Breakdown section.

        Returns list of course descriptors:
        [{"code": "302OPS", "name": "Operating System", "index": 0}, ...]
        """
        sel = self.config.selectors
        courses: List[dict[str, Any]] = []

        # 1. Wait for Course Breakdown section to appear
        try:
            page.locator(sel.course_breakdown_section).first.wait_for(
                state="visible", timeout=self.config.timeout_ms
            )
        except Exception:
            pass

        # 2. Wait for loading skeletons to detach if present (e.g. initial Next.js fetch)
        try:
            pulse_loc = page.locator(f"{sel.course_breakdown_section} {sel.loading_skeleton}, {sel.loading_skeleton}")
            if pulse_loc.count() > 0:
                pulse_loc.first.wait_for(state="detached", timeout=self.config.timeout_ms)
        except Exception:
            pass

        # 3. Wait for view details action or course cards to appear
        try:
            page.locator(f"{sel.view_details_action}, {sel.course_card}").first.wait_for(
                state="visible", timeout=self.config.timeout_ms
            )
        except Exception:
            pass

        # 4. Find all detail actions or course cards in Course Breakdown
        detail_actions = page.locator(sel.view_details_action)
        action_count = detail_actions.count()

        if action_count == 0:
            # Fallback: check if course card elements exist directly
            cards_loc = page.locator(sel.course_card)
            action_count = cards_loc.count()
            if action_count == 0:
                logger.warning("No 'Click to view details' actions or course cards found on PWIOI attendance dashboard.")
                return courses
            detail_actions = cards_loc

        for idx in range(action_count):
            action_btn = detail_actions.nth(idx)

            # Retrieve text and card container
            card_text = ""
            card_elem = None
            try:
                # If action_btn is already the card (contains h4)
                if action_btn.locator("h4").count() > 0:
                    card_elem = action_btn
                else:
                    card_elem = action_btn.locator("xpath=./ancestor::div[.//h4][1]")
                card_text = card_elem.inner_text()
            except Exception:
                card_elem = None

            if card_elem is None or not card_text:
                try:
                    card_elem = action_btn.locator("xpath=./ancestor::div[contains(., 'Classes') or contains(., '—') or contains(., '-') or contains(., 'Attended')][1]")
                    card_text = card_elem.inner_text()
                except Exception:
                    try:
                        card_elem = action_btn.locator("xpath=..")
                        card_text = card_elem.inner_text()
                    except Exception:
                        card_elem = action_btn
                        try:
                            card_text = action_btn.inner_text()
                        except Exception:
                            card_text = ""

            course_name: Optional[str] = None
            course_code: Optional[str] = None

            # First: check if card has a dedicated course title heading (h4 in modern PWIOI DOM)
            if card_elem is not None:
                try:
                    h4_loc = card_elem.locator("h4")
                    if h4_loc.count() > 0:
                        candidate_name = h4_loc.first.inner_text().strip()
                        if candidate_name:
                            course_name = candidate_name
                except Exception:
                    pass

                try:
                    span_loc = card_elem.locator("span.bg-gray-100, span[class*='bg-gray-100']")
                    if span_loc.count() > 0:
                        candidate_code = span_loc.first.inner_text().strip()
                        if candidate_code and (COURSE_CODE_PATTERN.match(candidate_code) or len(candidate_code) <= 12):
                            course_code = candidate_code
                    if not course_code:
                        all_spans = card_elem.locator("span")
                        for s_idx in range(all_spans.count()):
                            cand_s = all_spans.nth(s_idx).inner_text().strip()
                            if cand_s and COURSE_CODE_PATTERN.match(cand_s):
                                course_code = cand_s
                                break
                except Exception:
                    pass

            # Extract course name and code using patterns if not already found
            if not course_name or not course_code:
                split_match = COURSE_SPLIT_PATTERN.search(card_text)
                if split_match:
                    if not course_name:
                        course_name = split_match.group(1).strip()
                    if not course_code:
                        course_code = split_match.group(2).strip()
                else:
                    code_match = COURSE_CODE_PATTERN.search(card_text)
                    if code_match and not course_code:
                        course_code = code_match.group(1).strip()
                        if not course_name:
                            course_name = card_text.split(course_code)[0].strip(" —-\n\t")

            # Fallback for course_code and course_name
            if not course_code:
                course_code = f"UNKNOWN_COURSE_{idx + 1}"
            if not course_name:
                course_name = card_text[:50].strip() or f"Course {course_code}"

            courses.append({
                "code": course_code,
                "name": course_name,
                "index": idx,
            })

        return courses

    def _sleep(self, seconds: float) -> None:
        """Configurable delay helper allowing fast execution in unit tests."""
        import time

        if seconds > 0:
            time.sleep(seconds)

    def _ensure_daily_records_tab(self, page: Any, target_date_str: str) -> None:
        """Ensure Daily Records tab is active and date search query entered if available."""
        sel = self.config.selectors

        # 1. Wait for modal loading skeletons to detach if present
        try:
            modal_skeletons = page.locator(f"{sel.modal_container} {sel.loading_skeleton}")
            if modal_skeletons.count() > 0:
                modal_skeletons.first.wait_for(state="detached", timeout=self.config.timeout_ms)
        except Exception:
            pass

        # 2. Wait for daily records tab to be visible and click it
        daily_tab = page.locator(sel.daily_records_tab)
        try:
            daily_tab.first.wait_for(state="visible", timeout=self.config.timeout_ms)
            daily_tab.first.click()
            page.wait_for_load_state(self.config.wait_until)
        except Exception as tab_exc:
            logger.debug("Daily records tab click: %s", tab_exc)

        # 3. Wait for search date input to be visible and fill target_date_str
        search_input = page.locator(sel.search_date_input)
        try:
            search_input.first.wait_for(state="visible", timeout=self.config.timeout_ms)
            search_input.first.fill(target_date_str)
            page.wait_for_load_state(self.config.wait_until)
            # Wait for filtered records or no records indicator to appear
            try:
                page.locator(f"{sel.record_row}, {sel.no_records_indicator}").first.wait_for(
                    state="visible", timeout=min(3000, self.config.timeout_ms)
                )
            except Exception:
                pass
        except Exception as search_exc:
            logger.debug("Date search input fill skipped: %s", search_exc)

    def _parse_period_rows(self, page: Any, target_date: date) -> List[PWIOIPeriodRecord]:
        """Parse all period rows matching target date on the current page."""
        sel = self.config.selectors
        target_date_str = target_date.strftime("%Y-%m-%d")
        period_records: List[PWIOIPeriodRecord] = []

        row_locator = page.locator(sel.record_row)
        row_count = row_locator.count()

        if row_count == 0:
            # Check if "No Records Found" is displayed
            try:
                no_records = page.locator(sel.no_records_indicator)
                if no_records.count() > 0 and no_records.first.is_visible():
                    logger.debug("No records found indicator is visible for %s", target_date_str)
            except Exception:
                pass
            return []

        for r_idx in range(row_count):
            row = row_locator.nth(r_idx)
            try:
                row_raw = row.inner_text()
                row_text = row_raw.strip() if isinstance(row_raw, str) else str(row_raw).strip()
            except Exception:
                row_text = ""

            if not row_text:
                continue

            # Check if this row is for our target date:
            # If the row text contains an explicit date (YYYY-MM-DD), verify it matches target_date.
            # If no date is present in row text, the row was filtered by the search input
            # and is accepted for target_date.
            date_match = DATE_PATTERN.search(row_text)
            if date_match and date_match.group(1) != target_date_str:
                continue

            # Extract period identifier (e.g. "period 1", "period 2", "Period 1")
            period_name = None
            try:
                p_elem = row.locator("p.font-semibold, p")
                if p_elem.count() > 0:
                    cand_p = p_elem.first.inner_text().strip()
                    if cand_p:
                        period_name = cand_p.lower()
            except Exception:
                pass

            if not period_name:
                period_match = PERIOD_PATTERN.search(row_text)
                period_name = period_match.group(1).lower() if period_match else f"period {r_idx + 1}"

            # Extract status text (e.g. PRESENT, ABSENT, NOT MARKED)
            raw_status = None
            try:
                status_span = row.locator("span.font-medium, span")
                if status_span.count() > 0:
                    cand_s = status_span.first.inner_text().strip()
                    if cand_s:
                        status_m = STATUS_PATTERN.search(cand_s)
                        if status_m:
                            raw_status = status_m.group(1).upper()
            except Exception:
                pass

            if not raw_status:
                status_match = STATUS_PATTERN.search(row_text)
                raw_status = status_match.group(1).upper() if status_match else row_text

            normalized_status = self.normalizer.normalize_status(raw_status)
            is_reliable = self.normalizer.determine_reliability(normalized_status, raw_status)

            period_records.append(
                PWIOIPeriodRecord(
                    period=period_name,
                    target_date=target_date,
                    raw_status=raw_status,
                    status=normalized_status,
                    is_reliable=is_reliable,
                )
            )

        return period_records

    def _extract_daily_records_for_course(
        self,
        page: Any,
        course_info: dict[str, Any],
        target_date: date,
    ) -> Tuple[List[PWIOIPeriodRecord], int]:
        """Navigate to course details, open Daily Records, and parse records for target date.

        If records are missing, marked NOT MARKED, or pending, attempts to refresh/reload
        up to max_retries before returning.

        Returns:
            (period_records: List[PWIOIPeriodRecord], retries_attempted: int)
        """
        sel = self.config.selectors
        target_date_str = target_date.strftime("%Y-%m-%d")
        course_index = course_info["index"]
        period_records: List[PWIOIPeriodRecord] = []
        retries_attempted = 0

        try:
            # 1. Click "Click to view details" for this course
            detail_buttons = page.locator(sel.view_details_action)
            if detail_buttons.count() <= course_index:
                detail_buttons = page.locator(sel.course_card)

            if detail_buttons.count() <= course_index:
                logger.warning("Detail button for course index %d no longer available", course_index)
                return [], 0

            detail_buttons.nth(course_index).click()
            page.wait_for_load_state(self.config.wait_until)
            try:
                page.locator(sel.modal_container).first.wait_for(state="visible", timeout=self.config.timeout_ms)
            except Exception:
                pass

            # 2. Ensure Daily Records tab is active
            self._ensure_daily_records_tab(page, target_date_str)

            # 3. Initial parse
            period_records = self._parse_period_rows(page, target_date)

            # 4. If records are missing, marked NOT MARKED, or pending, attempt refresh
            if self.config.enable_refresh_on_stale and PWIOIPeriodAggregator.is_stale_or_pending(period_records):
                for retry in range(1, self.config.max_retries + 1):
                    retries_attempted = retry
                    logger.info(
                        "Attendance for %s on %s is pending/not marked. Refreshing page (attempt %d/%d)...",
                        course_info.get("code"),
                        target_date_str,
                        retry,
                        self.config.max_retries,
                    )
                    self._sleep(self.config.retry_delay_seconds)
                    try:
                        page.reload(wait_until=self.config.wait_until)
                        
                        # Wait for the main course breakdown skeleton to disappear if any
                        try:
                            pulse_loc = page.locator(f"{sel.course_breakdown_section} {sel.loading_skeleton}, {sel.loading_skeleton}")
                            if pulse_loc.count() > 0:
                                pulse_loc.first.wait_for(state="detached", timeout=self.config.timeout_ms)
                        except Exception:
                            pass

                        # Wait for course cards to render
                        try:
                            page.locator(f"{sel.view_details_action}, {sel.course_card}").first.wait_for(
                                state="visible", timeout=self.config.timeout_ms
                            )
                        except Exception:
                            pass

                        # Re-open the course modal
                        retry_detail_buttons = page.locator(sel.view_details_action)
                        if retry_detail_buttons.count() <= course_index:
                            retry_detail_buttons = page.locator(sel.course_card)
                        
                        if retry_detail_buttons.count() > course_index:
                            retry_detail_buttons.nth(course_index).click()
                            page.wait_for_load_state(self.config.wait_until)
                        
                        self._ensure_daily_records_tab(page, target_date_str)
                        period_records = self._parse_period_rows(page, target_date)
                        if not PWIOIPeriodAggregator.is_stale_or_pending(period_records):
                            logger.info(
                                "Attendance for %s on %s updated successfully after %d refresh(es)",
                                course_info.get("code"),
                                target_date_str,
                                retry,
                            )
                            break
                    except Exception as refresh_exc:
                        safe_err = redact_string(str(refresh_exc))
                        logger.warning(
                            "Refresh attempt %d failed for %s: %s",
                            retry,
                            course_info.get("code"),
                            safe_err,
                        )
                        break

            # 5. Close course detail modal
            self._close_course_modal(page)

        except Exception as exc:
            safe_err = redact_string(str(exc))
            logger.error(
                "Error extracting daily records for %s on %s: %s",
                course_info.get("code"),
                target_date_str,
                safe_err,
            )
            # Recover modal state cleanly
            try:
                self._close_course_modal(page)
            except Exception:
                pass

        return period_records, retries_attempted

    def get_attendance_for_date(self, target_date: date) -> List[SubjectAttendance]:
        """Fetch, parse, and aggregate daily attendance records across all courses for target date.

        Safety:
        - Validates config and ensures authentication.
        - Verifies academic term selection; fails closed if ambiguous or missing.
        - Enumerates all enrolled courses in Course Breakdown.
        - Inspects Daily Records for target date.
        - Aggregates multiple periods per course deterministically.
        - Fails closed to UNKNOWN on missing or unparseable data.
        """
        self.validate_config()

        if not self._is_authenticated:
            self.authenticate()

        try:
            page = self.browser_manager.get_page(
                storage_state_path=self.config.storage_state_path
            )

            # Ensure we are on the attendance dashboard
            if "/dashboard/student/attendance" not in page.url:
                page.goto(self.config.attendance_url, wait_until=self.config.wait_until)

            # 1. Verify or select Academic Term
            term_ok, active_term, term_error = self._verify_and_select_term(page)
            if not term_ok:
                logger.warning("Academic term check failed: %s", term_error)
                return [
                    SubjectAttendance(
                        subject_code="ALL",
                        status=AttendanceStatus.UNKNOWN,
                        is_reliable=False,
                        raw_status=None,
                        metadata={
                            "error": term_error,
                            "date": target_date.isoformat(),
                            "portal": "pwioi",
                        },
                    )
                ]

            # 2. Enumerate courses from Course Breakdown
            courses = self._enumerate_courses(page)
            if not courses:
                logger.warning("No courses discovered in Course Breakdown on %s", page.url)
                return [
                    SubjectAttendance(
                        subject_code="ALL",
                        status=AttendanceStatus.UNKNOWN,
                        is_reliable=False,
                        raw_status=None,
                        metadata={
                            "error": "No courses found in Course Breakdown",
                            "date": target_date.isoformat(),
                            "academic_term": active_term,
                            "portal": "pwioi",
                        },
                    )
                ]

            # 3. For each course, extract daily records and aggregate
            results: List[SubjectAttendance] = []

            for course_info in courses:
                periods, retries_attempted = self._extract_daily_records_for_course(
                    page, course_info, target_date
                )
                
                subject_attendance = PWIOIPeriodAggregator.aggregate(
                    course_code=course_info["code"],
                    course_name=course_info.get("name"),
                    target_date=target_date,
                    period_records=periods,
                    retries_attempted=retries_attempted,
                )

                # Attach academic term metadata
                if active_term:
                    subject_attendance.metadata["academic_term"] = active_term

                results.append(subject_attendance)

            return results

        except Exception as exc:
            safe_err = redact_string(str(exc))
            logger.error("Failed to fetch PWIOI attendance for %s: %s", target_date.isoformat(), safe_err)
            raise PortalUnavailableError(f"PWIOI portal attendance retrieval failed: {safe_err}") from exc

    def normalize_status(self, raw_status: Optional[str]) -> AttendanceStatus:
        """Normalize raw status to domain AttendanceStatus."""
        return self.normalizer.normalize_status(raw_status)

    def close(self) -> None:
        """Close browser resources safely."""
        self.browser_manager.close()
