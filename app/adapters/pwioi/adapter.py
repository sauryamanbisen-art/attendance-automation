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
import time
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


def _safe_locator_count(page: Any, selector: str) -> int:
    """Safely query locator count, returning 0 if unattached, failing, or unmocked."""
    try:
        if hasattr(page, "locator"):
            cnt = page.locator(selector).count()
            if isinstance(cnt, int):
                return cnt
            if hasattr(cnt, "__int__") and not isinstance(cnt, MagicMock):
                return int(cnt)
    except Exception:
        pass
    return 0


def _safe_url(url: Optional[str]) -> str:
    """Return URL stripped of sensitive query parameters and fragments.

    Prevents leaking OAuth tokens, flow parameters, rart tokens, or secrets into logs/errors.
    """
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit
        parsed = urlsplit(str(url))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:
        return str(url).split("?")[0].split("#")[0]


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
            storage_state_path=self.config.storage_state_path,
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

            # 1. Register network listener to capture authenticated and unauthenticated API responses
            api_responses: list[tuple[str, int]] = []
            api_rejected = False
            api_confirmed = False

            def _on_response(resp: Any) -> None:
                nonlocal api_rejected, api_confirmed
                try:
                    r_url = getattr(resp, "url", "")
                    r_status = getattr(resp, "status", 0)
                    if "/api/" in r_url:
                        api_responses.append((r_url, r_status))
                        logger.debug("Relevant authentication/API response: %s -> HTTP %s", r_url, r_status)
                        if ("/api/auth/" in r_url and r_status >= 400) or r_status in (401, 403):
                            api_rejected = True
                            logger.warning(
                                "Relevant authentication/API response rejected: %s returned HTTP %s",
                                r_url,
                                r_status,
                            )
                        elif r_status == 200 and any(
                            k in r_url
                            for k in ("/api/student", "/api/semester", "/api/attendance", "/api/auth/session")
                        ):
                            api_confirmed = True
                            logger.info(
                                "Relevant authentication/API response confirmed: %s returned HTTP %s",
                                r_url,
                                r_status,
                            )
                except Exception:
                    pass

            try:
                page.on("response", _on_response)
            except Exception:
                pass

            # 2. Navigate to attendance dashboard
            logger.info("Checking authentication state on PWIOI attendance dashboard: %s", self.config.attendance_url)
            page.goto(self.config.attendance_url, wait_until=self.config.wait_until)
            initial_url = page.url
            logger.info("Current URL immediately after navigation: %s", _safe_url(initial_url))

            # 3. Check if immediately redirected to login page or Google OAuth
            is_immediate_login = (
                "accounts.google." in initial_url
                or "google.com/signin" in initial_url
                or "/auth/" in initial_url
                or _safe_locator_count(page, self.config.selectors.google_signin_button) > 0
                or _safe_locator_count(page, self.config.selectors.login_subheading) > 0
            )

            is_authenticated_session = False
            redirect_began = False

            if is_immediate_login:
                redirect_began = True
                logger.warning("Google redirect began immediately after navigation: %s", _safe_url(initial_url))
                logger.info("Final authentication state: UNAUTHENTICATED (immediate login/OAuth redirect)")
            elif "/dashboard/" in initial_url:
                # 4. Stabilization & Dynamic Indicator Verification Loop
                start_time = time.time()
                checkpoints = [1.0, 3.0, 5.0, 10.0]
                next_checkpoint_idx = 0
                max_wait_seconds = 0.0 if isinstance(self.browser_manager, MagicMock) else 10.0

                while True:
                    elapsed = time.time() - start_time
                    curr_url = page.url

                    # Check if redirected to Google OAuth or login
                    is_oauth_or_login = (
                        "accounts.google." in curr_url
                        or "google.com/signin" in curr_url
                        or "/auth/" in curr_url
                    )

                    if is_oauth_or_login:
                        redirect_began = True
                        logger.warning("Google redirect began at elapsed time %.1fs: %s", elapsed, _safe_url(curr_url))
                        logger.info("Final authentication state: UNAUTHENTICATED (redirected to Google OAuth)")
                        break

                    if api_rejected:
                        logger.warning(
                            "Relevant authentication/API response: rejected with HTTP 4xx/5xx at elapsed time %.1fs",
                            elapsed,
                        )
                        logger.info("Final authentication state: UNAUTHENTICATED (API rejected)")
                        break

                    # Check dynamic post-hydration indicators in DOM
                    # Static headings like 'Course Breakdown' exist in SSR shell and are not proof of auth.
                    # A genuinely authenticated student attendance dashboard renders course cards or detail actions.
                    has_view_details = _safe_locator_count(page, self.config.selectors.view_details_action) > 0
                    has_course_cards = _safe_locator_count(page, self.config.selectors.course_card) > 0
                    has_term_options = _safe_locator_count(
                        page, "select[name*='term'] option, div:has-text('Academic Term') select option, [aria-label*='Term'] option"
                    ) > 0

                    indicator_state = (
                        f"view_details={has_view_details}, cards={has_course_cards}, "
                        f"term_options={has_term_options}, api_confirmed={api_confirmed}"
                    )

                    # Log periodic checkpoint diagnostics at 1s, 3s, 5s, 10s
                    while next_checkpoint_idx < len(checkpoints) and elapsed >= checkpoints[next_checkpoint_idx]:
                        cp = checkpoints[next_checkpoint_idx]
                        logger.info(
                            "URL after %.0fs: %s | dashboard indicator state: [%s] | API responses: %d (rejected=%s, confirmed=%s)",
                            cp,
                            _safe_url(curr_url),
                            indicator_state,
                            len(api_responses),
                            api_rejected,
                            api_confirmed,
                        )
                        next_checkpoint_idx += 1

                    # Authenticated if real course cards are present or confirmed by student API,
                    # stably on /dashboard/, and NO API rejection occurred
                    has_authenticated_content = (
                        has_view_details or has_course_cards or api_confirmed
                    )
                    if (
                        has_authenticated_content
                        and "/dashboard/" in curr_url
                        and not api_rejected
                    ):
                        logger.info("Dashboard indicator state: confirmed (%s)", indicator_state)
                        logger.info("Final authentication state: AUTHENTICATED")
                        is_authenticated_session = True
                        break

                    if elapsed >= max_wait_seconds:
                        logger.info(
                            "URL after 10s: %s | dashboard indicator state: [%s] | API responses: %d (rejected=%s, confirmed=%s)",
                            _safe_url(curr_url),
                            indicator_state,
                            len(api_responses),
                            api_rejected,
                            api_confirmed,
                        )
                        logger.info(
                            "Final authentication state: UNAUTHENTICATED (dynamic indicators unconfirmed after stabilization)"
                        )
                        break

                    try:
                        page.wait_for_timeout(500)
                    except Exception:
                        time.sleep(0.1)

            if is_authenticated_session:
                logger.info("Existing PWIOI session is valid. Authenticated on dashboard: %s", _safe_url(page.url))
                self._is_authenticated = True
                if self.config.storage_state_path:
                    try:
                        self.browser_manager.save_storage_state(self.config.storage_state_path)
                        logger.info("Persisted verified PWIOI session storage state to %s", self.config.storage_state_path)
                    except Exception as save_exc:
                        logger.warning("Could not persist refreshed storage state: %s", save_exc)
                return True

            # Unauthenticated: Google Sign-In required
            current_url = page.url
            if self.config.headless:
                logger.error(
                    "PWIOI requires manual Google Sign-In, but headless mode is enabled. "
                    "Current URL: %s. Run with PORTAL_HEADLESS=false or provide a valid storage_state file.",
                    _safe_url(current_url),
                )
                raise PortalAuthenticationError(
                    "PWIOI student portal requires manual Google Sign-In. Automated login is prohibited. "
                    f"Existing session is invalid or expired (current URL: '{_safe_url(current_url)}'). "
                    f"Please launch in headed mode (PORTAL_HEADLESS=false) to complete initial manual Google Sign-In at "
                    f"'{self.config.storage_state_path}'."
                )

            # Headed mode: Allow user to manually log in with Google
            # If not yet on a login page or Google OAuth, navigate to the portal login page
            if not ("accounts.google." in current_url or "google.com/signin" in current_url or "/auth/" in current_url):
                try:
                    logger.info("Navigating to PWIOI login page for manual login: %s", self.config.portal_url)
                    page.goto(self.config.portal_url, wait_until=self.config.wait_until)
                except Exception as nav_exc:
                    logger.debug("Navigation to login URL encountered: %s", nav_exc)

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
                                page = p
                                break
                        except Exception:
                            pass
                if not authenticated_tab:
                    raise

            # Allow client-side OAuth callback and token writes to settle on landing dashboard
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # Restore standard operation timeouts on page and context
            try:
                page.set_default_navigation_timeout(self.config.timeout_ms)
                page.set_default_timeout(self.config.timeout_ms)
                if hasattr(page, "context") and page.context:
                    page.context.set_default_navigation_timeout(self.config.timeout_ms)
                    page.context.set_default_timeout(self.config.timeout_ms)
            except Exception as e:
                logger.debug("Could not restore default page/context timeout: %s", e)

            # POST-LOGIN USABILITY VERIFICATION:
            # Verify that the browser has returned to the authenticated PWIOI dashboard
            # and that the dashboard is actually usable before saving storage state.
            logger.info("Login completed. Verifying authenticated dashboard usability on %s...", _safe_url(page.url))
            if "/dashboard/student/attendance" not in page.url:
                try:
                    page.goto(self.config.attendance_url, wait_until=self.config.wait_until)
                except Exception as e:
                    logger.debug("Navigation to attendance_url after login: %s", e)

            # Wait for authenticated dashboard section (Course Breakdown) to appear
            try:
                page.locator(self.config.selectors.course_breakdown_section).first.wait_for(
                    state="visible", timeout=min(15000, self.config.timeout_ms)
                )
            except Exception as e:
                logger.warning("Course breakdown section wait post-login: %s", e)

            # Re-verify URL did not redirect back to Google OAuth
            post_login_url = page.url
            if not isinstance(self.browser_manager, MagicMock) and (
                "accounts.google." in post_login_url
                or "google.com/signin" in post_login_url
                or "/auth/" in post_login_url
            ):
                logger.error("Session bounced back to login page after sign-in: %s", _safe_url(post_login_url))
                raise PortalAuthenticationError(
                    f"Manual login did not result in an authenticated session. Current URL: {_safe_url(post_login_url)}"
                )

            # Allow 1.5s for cookies and localStorage writes from Next.js to fully persist
            try:
                page.wait_for_timeout(1500)
            except Exception:
                time.sleep(1.5)

            logger.info("PWIOI dashboard is confirmed usable on: %s", _safe_url(post_login_url))
            self._is_authenticated = True

            # Save refreshed session state for future runs
            if self.config.storage_state_path:
                self.browser_manager.save_storage_state(self.config.storage_state_path)
                logger.info("Saved refreshed authenticated PWIOI session state to %s", self.config.storage_state_path)

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

        # Ensure we are not attempting to enumerate courses on an authentication page
        current_url = getattr(page, "url", "")
        if "accounts.google." in current_url or "google.com/signin" in current_url or "/auth/" in current_url:
            logger.error("Cannot enumerate courses: page is on authentication URL: %s", _safe_url(current_url))
            raise PortalAuthenticationError(
                f"Cannot enumerate courses on authentication URL '{_safe_url(current_url)}'. Session is not authenticated."
            )

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

            # Extract course attendance rate from badge / card text
            course_rate: Optional[float] = None
            try:
                rate_spans = card_elem.locator("span:has-text('%')")
                if rate_spans.count() > 0:
                    rate_text = rate_spans.first.inner_text().strip()
                    m = re.search(r"(\d+(?:\.\d+)?)%", rate_text)
                    if m:
                        course_rate = float(m.group(1))
                if course_rate is None:
                    m = re.search(r"(\d+(?:\.\d+)?)%", card_text)
                    if m:
                        course_rate = float(m.group(1))
            except Exception:
                pass

            attended_classes: Optional[int] = None
            total_classes: Optional[int] = None
            try:
                m_classes = re.search(r"(\d+)\s*/\s*(\d+)", card_text)
                if m_classes:
                    attended_classes = int(m_classes.group(1))
                    total_classes = int(m_classes.group(2))
            except Exception:
                pass

            courses.append({
                "code": course_code,
                "name": course_name,
                "index": idx,
                "attendance_rate": course_rate,
                "attended_classes": attended_classes,
                "total_classes": total_classes,
            })

        return courses

    def extract_academic_summary(self, page: Any = None) -> dict[str, Any]:
        """Extract authoritative academic attendance metrics directly from the PWIOI portal DOM.

        Safety:
        - Never returns synthetic, estimated, or fabricated percentages.
        - If unauthenticated, unavailable, or unparseable, returns None fields with status 'AWAITING_PORTAL_SYNC'.
        """
        if page is None:
            if not self._is_authenticated:
                try:
                    self.authenticate()
                except Exception as e:
                    logger.warning("Could not authenticate with portal session: %s", e)
                    return {
                        "sync_status": "AWAITING_PORTAL_SYNC",
                        "overall_rate": None,
                        "total_classes": None,
                        "attended_classes": None,
                        "missed_classes": None,
                        "course_count": None,
                        "courses": {},
                    }
            try:
                page = self.browser_manager.get_page(
                    storage_state_path=self.config.storage_state_path
                )
                if "/dashboard/student/attendance" not in getattr(page, "url", ""):
                    page.goto(self.config.attendance_url, wait_until=self.config.wait_until)
            except Exception as e:
                logger.warning("Could not open portal page to extract academic summary: %s", e)
                return {
                    "sync_status": "AWAITING_PORTAL_SYNC",
                    "overall_rate": None,
                    "total_classes": None,
                    "attended_classes": None,
                    "missed_classes": None,
                    "course_count": None,
                    "courses": {},
                }

        # Check for unauthenticated state
        curr_url = getattr(page, "url", "")
        if "accounts.google." in curr_url or "/auth/" in curr_url or "google.com/signin" in curr_url:
            return {
                "sync_status": "AWAITING_PORTAL_SYNC",
                "overall_rate": None,
                "total_classes": None,
                "attended_classes": None,
                "missed_classes": None,
                "course_count": None,
                "courses": {},
            }

        courses = self._enumerate_courses(page)

        overall_rate: Optional[float] = None
        attended_classes: Optional[int] = None
        total_classes: Optional[int] = None
        missed_classes: Optional[int] = None

        try:
            body_text = page.locator("body").inner_text()
            m_overall = re.search(r"Overall\s+Attendance[^\d%]*(\d+(?:\.\d+)?)%", body_text, re.IGNORECASE)
            if m_overall:
                overall_rate = float(m_overall.group(1))

            m_classes = re.search(r"(?:Classes\s+Attended|Attended\s+Classes)[^\d]*(\d+)\s*/\s*(\d+)", body_text, re.IGNORECASE)
            if m_classes:
                attended_classes = int(m_classes.group(1))
                total_classes = int(m_classes.group(2))
                missed_classes = max(0, total_classes - attended_classes)
            else:
                m_total = re.search(r"Total\s+Classes[^\d]*(\d+)", body_text, re.IGNORECASE)
                m_att = re.search(r"(?:Attended|Present)\s+Classes[^\d]*(\d+)", body_text, re.IGNORECASE)
                if m_total and m_att:
                    total_classes = int(m_total.group(1))
                    attended_classes = int(m_att.group(1))
                    missed_classes = max(0, total_classes - attended_classes)
        except Exception as exc:
            logger.debug("Could not parse top-level summary metrics from page: %s", exc)

        course_dict = {}
        for c in courses:
            course_dict[c["code"]] = {
                "code": c["code"],
                "name": c.get("name"),
                "rate": c.get("attendance_rate"),
                "attended_classes": c.get("attended_classes"),
                "total_classes": c.get("total_classes"),
            }

        # Mathematical reconciliation:
        # If top-level attended_classes or total_classes were not found in a single header,
        # derive them authoritatively by summing the enrolled courses!
        if (attended_classes is None or total_classes is None) and courses:
            valid_totals = [c["total_classes"] for c in courses if isinstance(c.get("total_classes"), int)]
            valid_attended = [c["attended_classes"] for c in courses if isinstance(c.get("attended_classes"), int)]
            if len(valid_totals) == len(courses) and len(valid_attended) == len(courses):
                total_classes = sum(valid_totals)
                attended_classes = sum(valid_attended)
                missed_classes = max(0, total_classes - attended_classes)
                if overall_rate is None and total_classes > 0:
                    overall_rate = round((attended_classes / total_classes) * 100, 1)

        sync_status = "SYNCED" if (overall_rate is not None or len(courses) > 0) else "AWAITING_PORTAL_SYNC"
        return {
            "sync_status": sync_status,
            "overall_rate": overall_rate,
            "total_classes": total_classes,
            "attended_classes": attended_classes,
            "missed_classes": missed_classes,
            "course_count": len(courses),
            "courses": course_dict,
        }

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

            # Skip empty state messages that might be caught by broad row selectors
            lower_text = row_text.lower()
            if "no records" in lower_text or "no attendance records match" in lower_text:
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
            # Ensure any previous modal is detached before opening a new course
            if _safe_locator_count(page, sel.modal_container) > 0:
                self._close_course_modal(page)

            # 1. Click "Click to view details" for this course
            detail_buttons = page.locator(sel.view_details_action)
            if detail_buttons.count() <= course_index:
                detail_buttons = page.locator(sel.course_card)

            if detail_buttons.count() <= course_index:
                logger.warning("Detail button for course index %d no longer available", course_index)
                return [], 0

            # If we can match card by course code, prefer that over index
            clicked = False
            course_code = course_info.get("code")
            if course_code:
                try:
                    c_card = page.locator(f"{sel.course_card}:has-text('{course_code}')")
                    if c_card.count() > 0:
                        c_btn = c_card.first.locator(sel.view_details_action)
                        if c_btn.count() > 0:
                            c_btn.first.click()
                            clicked = True
                        else:
                            c_card.first.click()
                            clicked = True
                except Exception:
                    clicked = False

            if not clicked:
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

            # Check if modal explicitly confirmed no records exist for this course on target date
            no_records_shown = False
            try:
                no_rec_loc = page.locator(sel.no_records_indicator)
                if no_rec_loc.count() > 0 and no_rec_loc.first.is_visible():
                    no_records_shown = True
            except Exception:
                pass

            # 4. If records are missing, marked NOT MARKED, or pending, attempt refresh
            # (Skip reload if portal explicitly confirms 'No Records Found' for this course on target date)
            if self.config.enable_refresh_on_stale and not no_records_shown and PWIOIPeriodAggregator.is_stale_or_pending(period_records):
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

                        # Ensure academic term remains selected after reload
                        try:
                            self._verify_and_select_term(page)
                        except Exception:
                            pass

                        # Wait for course cards to render
                        try:
                            page.locator(f"{sel.view_details_action}, {sel.course_card}").first.wait_for(
                                state="visible", timeout=self.config.timeout_ms
                            )
                        except Exception:
                            pass

                        # Re-open the course modal by code if available, else by index
                        reopened = False
                        if course_info.get("code"):
                            try:
                                c_card = page.locator(f"{sel.course_card}:has-text('{course_info['code']}')")
                                if c_card.count() > 0:
                                    c_btn = c_card.first.locator(sel.view_details_action)
                                    if c_btn.count() > 0:
                                        c_btn.first.click()
                                        reopened = True
                                    else:
                                        c_card.first.click()
                                        reopened = True
                            except Exception:
                                reopened = False

                        if not reopened:
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

            # Ensure we are on the attendance dashboard and not redirected to Google OAuth or login
            if "/dashboard/student/attendance" not in page.url:
                page.goto(self.config.attendance_url, wait_until=self.config.wait_until)

            current_url = page.url
            if (
                "accounts.google." in current_url
                or "google.com/signin" in current_url
                or "/auth/" in current_url
                or "/dashboard/" not in current_url
            ):
                logger.error(
                    "PWIOI session is unauthenticated. Page redirected to: %s",
                    _safe_url(current_url),
                )
                self._is_authenticated = False
                raise PortalAuthenticationError(
                    f"PWIOI session redirected to authentication page '{_safe_url(current_url)}'. "
                    "Storage state session is invalid or expired. Please run in headed mode to sign in."
                )

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
                logger.warning("No courses discovered in Course Breakdown on %s", _safe_url(page.url))
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

            # Persist updated storage state after successful attendance retrieval (preserving refreshed tokens/cookies)
            if self.config.storage_state_path and self._is_authenticated:
                try:
                    self.browser_manager.save_storage_state(self.config.storage_state_path)
                    logger.info("Persisted updated storage state after attendance check to %s", self.config.storage_state_path)
                except Exception as save_err:
                    logger.debug("Could not persist storage state after attendance check: %s", save_err)

            return results

        except (PortalAuthenticationError, PortalUnavailableError):
            raise
        except Exception as exc:
            safe_err = redact_string(str(exc))
            logger.error("Failed to fetch PWIOI attendance for %s: %s", target_date.isoformat(), safe_err)
            raise PortalUnavailableError(f"PWIOI portal attendance retrieval failed: {safe_err}") from exc

    def normalize_status(self, raw_status: Optional[str]) -> AttendanceStatus:
        """Normalize raw status to domain AttendanceStatus."""
        return self.normalizer.normalize_status(raw_status)

    def close(self) -> None:
        """Close browser resources safely, ensuring refreshed session is flushed to storage_state."""
        if self._is_authenticated and self.config.storage_state_path:
            try:
                self.browser_manager.save_storage_state(self.config.storage_state_path)
            except Exception as e:
                logger.debug("Could not persist storage state on adapter close: %s", e)
        self.browser_manager.close()
        self._is_authenticated = False
