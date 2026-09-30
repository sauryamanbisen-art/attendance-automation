"""Unit tests for PWIOIPortalAdapter using mocked Playwright objects."""

from datetime import date
from unittest.mock import MagicMock, patch
import pytest

from app.adapters.base.adapter import (
    PortalAuthenticationError,
    PortalConfigurationError,
    PortalUnavailableError,
    SubjectAttendance,
)
from app.adapters.playwright.browser_manager import PlaywrightBrowserManager
from app.adapters.pwioi.adapter import PWIOIPortalAdapter
from app.adapters.pwioi.aggregator import PWIOIPeriodAggregator, PWIOIPeriodRecord
from app.adapters.pwioi.config import PWIOIPortalConfig
from app.core.enums import AttendanceStatus


class TestPWIOIPortalAdapter:
    """Validate PWIOIPortalAdapter authentication, term handling, and attendance extraction."""

    TARGET_DATE = date(2026, 8, 4)

    def test_adapter_properties(self):
        """Adapter must identify as 'pwioi' and enforce read-only safety."""
        adapter = PWIOIPortalAdapter()
        assert adapter.adapter_name == "pwioi"
        assert adapter.is_read_only is True

    def test_adapter_initializes_browser_manager_with_browser_channel(self):
        cfg = PWIOIPortalConfig(browser_channel="chrome")
        adapter = PWIOIPortalAdapter(config=cfg)
        assert adapter.browser_manager.browser_channel == "chrome"

    def test_adapter_initializes_browser_manager_without_channel_by_default(self):
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)
        assert adapter.browser_manager.browser_channel is None

    def test_validate_config_delegates(self):
        """validate_config() invokes config.validate()."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)
        assert adapter.validate_config() is True

        bad_cfg = PWIOIPortalConfig(portal_url="")
        bad_adapter = PWIOIPortalAdapter(config=bad_cfg)
        with pytest.raises(PortalConfigurationError):
            bad_adapter.validate_config()

    def test_authenticate_existing_session_valid(self):
        """When dashboard URL is active and no login button is visible, session is valid."""
        cfg = PWIOIPortalConfig()
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/dashboard/student/attendance"

        # Mock absence of login indicators
        def locator_mock(selector):
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        assert adapter.authenticate() is True
        assert adapter._is_authenticated is True

    def test_authenticate_unauthenticated_headless_raises_error(self):
        """If user is not logged in and headless=True, fail closed with informative error."""
        cfg = PWIOIPortalConfig(headless=True)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/auth/student/login"

        # Mock presence of Google sign-in button
        def locator_mock(selector):
            loc = MagicMock()
            if "Google" in selector or "dashboard" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        with pytest.raises(PortalAuthenticationError, match="manual Google Sign-In"):
            adapter.authenticate()

    def test_authenticate_headed_manual_login_success(self):
        """In headed mode (headless=False), allows manual login, waits up to 5 minutes, and saves storage state."""
        cfg = PWIOIPortalConfig(headless=False, storage_state_path="storage_state/test_pwioi.json")
        assert cfg.manual_login_timeout_ms == 300000
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/auth/student/login"

        def locator_mock(selector):
            loc = MagicMock()
            if "Google" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        assert adapter.authenticate() is True
        assert adapter._is_authenticated is True
        mock_page.wait_for_url.assert_called_once()
        args, kwargs = mock_page.wait_for_url.call_args
        assert kwargs.get("timeout") == 300000
        mock_bm.save_storage_state.assert_called_once_with("storage_state/test_pwioi.json")

    def test_authenticate_headed_manual_login_secondary_tab_fallback(self):
        """If main page wait_for_url fails but a secondary popup/tab reaches /dashboard/student, succeed."""
        cfg = PWIOIPortalConfig(headless=False, storage_state_path="storage_state/test_pwioi.json")
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/auth/student/login"

        # Simulate wait_for_url timing out on main page
        mock_page.wait_for_url.side_effect = Exception("Timeout waiting for URL")

        # Mock secondary page/popup that reached dashboard
        popup_page = MagicMock()
        popup_page.is_closed.return_value = False
        popup_page.url = "https://app.pwioi.club/dashboard/student"

        mock_context = MagicMock()
        mock_context.pages = [mock_page, popup_page]
        mock_page.context = mock_context

        def locator_mock(selector):
            loc = MagicMock()
            if "Google" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        assert adapter.authenticate() is True
        assert adapter._is_authenticated is True
        mock_bm.save_storage_state.assert_called_once_with("storage_state/test_pwioi.json")

    def test_authenticate_headed_manual_login_timeout_fails_safely(self):
        """If 5-minute timeout expires and dashboard is not reached, raises PortalUnavailableError."""
        cfg = PWIOIPortalConfig(headless=False)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/auth/student/login"
        mock_page.wait_for_url.side_effect = Exception("Timeout 300000ms exceeded")

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_page.context = mock_context

        def locator_mock(selector):
            loc = MagicMock()
            if "Google" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        with pytest.raises(PortalUnavailableError, match="Could not reach or authenticate"):
            adapter.authenticate()


    def test_verify_and_select_term_select_matches(self):
        """Academic Term configured as '3' matches native select."""
        cfg = PWIOIPortalConfig(academic_term="3")
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        dropdown = MagicMock()
        dropdown.evaluate.return_value = "select"
        dropdown.input_value.return_value = "3"

        dropdown_loc = MagicMock()
        dropdown_loc.count.return_value = 1
        dropdown_loc.first = dropdown

        mock_page.locator.return_value = dropdown_loc

        ok, active_term, err = adapter._verify_and_select_term(mock_page)
        assert ok is True
        assert active_term == "3"
        assert err is None

    def test_verify_and_select_term_missing_fails_closed(self):
        """When configured Academic Term cannot be found, returns fail-closed tuple."""
        cfg = PWIOIPortalConfig(academic_term="5")
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        dropdown_loc = MagicMock()
        dropdown_loc.count.return_value = 0
        container_loc = MagicMock()
        container_loc.count.return_value = 0

        def locator_mock(sel):
            if "container" in sel or "Academic Term" in sel:
                return container_loc
            return dropdown_loc

        mock_page.locator.side_effect = locator_mock

        ok, active_term, err = adapter._verify_and_select_term(mock_page)
        assert ok is False
        assert active_term is None
        assert "could not be verified" in err

    def test_verify_and_select_term_auto_detects_when_none_configured(self):
        """When academic_term is None, auto-detects active term from page."""
        cfg = PWIOIPortalConfig(academic_term=None)
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        dropdown = MagicMock()
        dropdown.inner_text.return_value = "Term 3"
        dropdown_loc = MagicMock()
        dropdown_loc.count.return_value = 1
        dropdown_loc.first = dropdown
        mock_page.locator.return_value = dropdown_loc

        ok, active_term, err = adapter._verify_and_select_term(mock_page)
        assert ok is True
        assert active_term == "Term 3"
        assert err is None

    def test_verify_and_select_term_matches_option_text_with_uuid_value(self):
        """When select options have UUID values and digit text, matches active option text."""
        cfg = PWIOIPortalConfig(academic_term="3")
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        dropdown = MagicMock()
        dropdown.evaluate.side_effect = lambda script, *args: "select" if "tagName" in script else "3"
        dropdown.input_value.return_value = "66a1b2c3-uuid-4567"

        dropdown_loc = MagicMock()
        dropdown_loc.count.return_value = 1
        dropdown_loc.first = dropdown
        mock_page.locator.return_value = dropdown_loc

        ok, active_term, err = adapter._verify_and_select_term(mock_page)
        assert ok is True
        assert active_term == "3"
        assert err is None

    def test_verify_and_select_term_selects_by_label_candidate(self):
        """When not yet selected, selects candidate label '3' and updates active term."""
        cfg = PWIOIPortalConfig(academic_term="Term 3")
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        dropdown = MagicMock()
        eval_state = {"current_term": "1"}

        def eval_mock(script, *args):
            if "tagName" in script:
                return "select"
            return eval_state["current_term"]

        dropdown.evaluate.side_effect = eval_mock
        dropdown.input_value.return_value = "other-semester-uuid"

        def select_mock(**kwargs):
            eval_state["current_term"] = "3"
            return ["3"]

        dropdown.select_option.side_effect = select_mock

        dropdown_loc = MagicMock()
        dropdown_loc.count.return_value = 1
        dropdown_loc.first = dropdown
        mock_page.locator.return_value = dropdown_loc

        ok, active_term, err = adapter._verify_and_select_term(mock_page)
        assert ok is True
        assert active_term == "3"
        assert err is None
        dropdown.select_option.assert_called()


    def test_enumerate_courses_extracts_codes_and_names(self):
        """Extracts course codes and names correctly from Course Breakdown."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()

        # Simulate 2 course detail action buttons
        btn1 = MagicMock()
        ancestor1 = MagicMock()
        ancestor1.inner_text.return_value = "Operating System — 302OPS\nClasses Attended: 12/14\nClick to view details →"
        btn1.locator.return_value = ancestor1

        btn2 = MagicMock()
        ancestor2 = MagicMock()
        ancestor2.inner_text.return_value = "OJT / Java Web Developer (Spring Boot) — 306JWD\nClick to view details →"
        btn2.locator.return_value = ancestor2

        detail_actions = MagicMock()
        detail_actions.count.return_value = 2
        detail_actions.nth.side_effect = lambda idx: [btn1, btn2][idx]

        mock_page.locator.return_value = detail_actions

        courses = adapter._enumerate_courses(mock_page)
        assert len(courses) == 2
        assert courses[0]["code"] == "302OPS"
        assert courses[0]["name"] == "Operating System"
        assert courses[1]["code"] == "306JWD"
        assert courses[1]["name"] == "OJT / Java Web Developer (Spring Boot)"

    def test_enumerate_courses_empty_returns_empty_list(self):
        """If no course cards or detail actions exist, returns empty list."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        detail_actions = MagicMock()
        detail_actions.count.return_value = 0
        mock_page.locator.return_value = detail_actions

        courses = adapter._enumerate_courses(mock_page)
        assert courses == []

    def test_enumerate_courses_modern_dom_with_h4(self):
        """Extracts course codes and names correctly from modern PWIOI DOM with h4 title."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()

        card_elem = MagicMock()
        h4_elem = MagicMock()
        h4_elem.inner_text.return_value = "Advanced Data Structures & Algorithms"
        h4_loc = MagicMock()
        h4_loc.count.return_value = 1
        h4_loc.first = h4_elem

        def card_locator(query):
            if "h4" in query:
                return h4_loc
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        card_elem.locator.side_effect = card_locator
        card_elem.inner_text.return_value = "Advanced Data Structures & Algorithms\n301ADS 92.5%\nExcellent\n37/40\nClick to view details →"

        btn = MagicMock()
        btn.locator.return_value = card_elem

        detail_actions = MagicMock()
        detail_actions.count.return_value = 1
        detail_actions.nth.return_value = btn

        def page_locator(query):
            if "pulse" in query or "skeleton" in query:
                loc = MagicMock()
                loc.count.return_value = 0
                return loc
            return detail_actions

        mock_page.locator.side_effect = page_locator

        courses = adapter._enumerate_courses(mock_page)
        assert len(courses) == 1
        assert courses[0]["code"] == "301ADS"
        assert courses[0]["name"] == "Advanced Data Structures & Algorithms"

    def test_parse_period_rows_filtered_by_search_input_without_date_in_row(self):
        """Parses rows where search input filtered by date and row text contains only period and status."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()

        row1 = MagicMock()
        row1.inner_text.return_value = "Period 1\nPresent"
        row2 = MagicMock()
        row2.inner_text.return_value = "Period 2\nAbsent"

        rows_loc = MagicMock()
        rows_loc.count.return_value = 2
        rows_loc.nth.side_effect = lambda idx: [row1, row2][idx]

        mock_page.locator.return_value = rows_loc

        periods = adapter._parse_period_rows(mock_page, self.TARGET_DATE)
        assert len(periods) == 2
        assert periods[0].period == "period 1"
        assert periods[0].status == AttendanceStatus.PRESENT
        assert periods[0].is_reliable is True
        assert periods[1].period == "period 2"
        assert periods[1].status == AttendanceStatus.ABSENT
        assert periods[1].is_reliable is True

    def test_parse_period_rows_no_records_indicator_visible(self):
        """When 0 rows exist and No Records Found indicator is visible, returns empty list safely."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        rows_loc = MagicMock()
        rows_loc.count.return_value = 0

        no_rec_loc = MagicMock()
        no_rec_loc.count.return_value = 1
        no_rec_loc.first.is_visible.return_value = True

        def locator_mock(sel):
            if "No Records" in sel or "No attendance" in sel:
                return no_rec_loc
            return rows_loc

        mock_page.locator.side_effect = locator_mock

        periods = adapter._parse_period_rows(mock_page, self.TARGET_DATE)
        assert periods == []


    def test_close_course_modal_clicks_close_button(self):
        """Verifies _close_course_modal clicks modal close button."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        close_btn = MagicMock()
        close_loc = MagicMock()
        close_loc.count.return_value = 1
        close_loc.first = close_btn
        mock_page.locator.return_value = close_loc

        adapter._close_course_modal(mock_page)
        close_btn.click.assert_called_once()

    def test_extract_daily_records_parses_target_date(self):
        """Extracts records matching target date and ignores non-target dates."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()

        # Mock detail button click
        btn = MagicMock()
        detail_actions = MagicMock()
        detail_actions.count.return_value = 1
        detail_actions.nth.return_value = btn

        # Mock rows
        row1 = MagicMock()
        row1.inner_text.return_value = "2026-08-04-period 1   PRESENT"
        row2 = MagicMock()
        row2.inner_text.return_value = "2026-08-04-period 2   PRESENT"
        row3 = MagicMock()
        row3.inner_text.return_value = "2026-08-03-period 1   ABSENT"  # Different date

        rows_loc = MagicMock()
        rows_loc.count.return_value = 3
        rows_loc.nth.side_effect = lambda idx: [row1, row2, row3][idx]

        def locator_mock(sel):
            if "details" in sel:
                return detail_actions
            if "Daily Records" in sel:
                loc = MagicMock()
                loc.count.return_value = 1
                return loc
            if "Back" in sel:
                loc = MagicMock()
                loc.count.return_value = 1
                return loc
            return rows_loc

        mock_page.locator.side_effect = locator_mock

        course_info = {"code": "302OPS", "name": "Operating System", "index": 0}
        periods, retries = adapter._extract_daily_records_for_course(mock_page, course_info, self.TARGET_DATE)

        assert len(periods) == 2
        assert periods[0].period == "period 1"
        assert periods[0].status == AttendanceStatus.PRESENT
        assert periods[1].period == "period 2"
        assert periods[1].status == AttendanceStatus.PRESENT

    def test_get_attendance_for_date_term_failure_returns_unknown(self):
        """When Academic Term verification fails, returns diagnostic UNKNOWN record."""
        cfg = PWIOIPortalConfig(academic_term="4")
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/dashboard/student/attendance"

        # Term control not found
        term_loc = MagicMock()
        term_loc.count.return_value = 0
        mock_page.locator.return_value = term_loc
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        records = adapter.get_attendance_for_date(self.TARGET_DATE)
        assert len(records) == 1
        assert records[0].status == AttendanceStatus.UNKNOWN
        assert records[0].is_reliable is False
        assert "could not be verified" in records[0].metadata["error"]

    def test_get_attendance_for_date_no_courses_returns_unknown(self):
        """When no courses are found in Course Breakdown, returns diagnostic UNKNOWN record."""
        cfg = PWIOIPortalConfig(academic_term=None)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/dashboard/student/attendance"

        # Term ok
        term_dropdown = MagicMock()
        term_dropdown.inner_text.return_value = "Term 3"
        term_loc = MagicMock()
        term_loc.count.return_value = 1
        term_loc.first = term_dropdown

        # 0 courses
        courses_loc = MagicMock()
        courses_loc.count.return_value = 0

        def locator_mock(sel):
            if "term" in sel.lower():
                return term_loc
            return courses_loc

        mock_page.locator.side_effect = locator_mock
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        records = adapter.get_attendance_for_date(self.TARGET_DATE)
        assert len(records) == 1
        assert records[0].status == AttendanceStatus.UNKNOWN
        assert records[0].is_reliable is False
        assert "No courses found" in records[0].metadata["error"]

    def test_get_attendance_for_date_successful_aggregation(self):
        """End-to-end get_attendance_for_date with multiple courses and period aggregation."""
        cfg = PWIOIPortalConfig(academic_term=None)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://app.pwioi.club/dashboard/student/attendance"
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        # Mock term selection
        adapter._verify_and_select_term = MagicMock(return_value=(True, "Term 3", None))

        # Mock 2 courses
        adapter._enumerate_courses = MagicMock(return_value=[
            {"code": "302OPS", "name": "Operating System", "index": 0},
            {"code": "306JWD", "name": "Java Web Developer", "index": 1},
        ])

        from app.adapters.pwioi.aggregator import PWIOIPeriodRecord

        # Course 1 has period 1 & 2 PRESENT
        course1_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "PRESENT", AttendanceStatus.PRESENT, True),
            PWIOIPeriodRecord("period 2", self.TARGET_DATE, "PRESENT", AttendanceStatus.PRESENT, True),
        ]
        # Course 2 has period 1 ABSENT
        course2_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "ABSENT", AttendanceStatus.ABSENT, True),
        ]

        adapter._extract_daily_records_for_course = MagicMock(
            side_effect=lambda page, course, dt: (course1_periods, 0) if course["code"] == "302OPS" else (course2_periods, 0)
        )

        records = adapter.get_attendance_for_date(self.TARGET_DATE)
        assert len(records) == 2

        # 302OPS: all PRESENT -> PRESENT, reliable=True
        assert records[0].subject_code == "302OPS"
        assert records[0].status == AttendanceStatus.PRESENT
        assert records[0].is_reliable is True

        # 306JWD: period 1 ABSENT -> ABSENT, reliable=True
        assert records[1].subject_code == "306JWD"
        assert records[1].status == AttendanceStatus.ABSENT
        assert records[1].is_reliable is True
        assert records[1].metadata["absent_periods"] == ["period 1"]

    def test_get_attendance_for_date_network_error_raises_unavailable(self):
        """Page network or connection errors raise PortalUnavailableError."""
        cfg = PWIOIPortalConfig()
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("net::ERR_CONNECTION_REFUSED")
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        with pytest.raises(PortalUnavailableError, match="ERR_CONNECTION_REFUSED"):
            adapter.get_attendance_for_date(self.TARGET_DATE)

    def test_normalize_status_delegates(self):
        """normalize_status maps known and unknown status tokens safely."""
        adapter = PWIOIPortalAdapter()
        assert adapter.normalize_status("PRESENT") == AttendanceStatus.PRESENT
        assert adapter.normalize_status("ABSENT") == AttendanceStatus.ABSENT
        assert adapter.normalize_status("Medical Leave") == AttendanceStatus.UNKNOWN

    def test_close_cleans_up_browser_manager(self):
        """close() safely invokes browser_manager.close()."""
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        adapter = PWIOIPortalAdapter(browser_manager=mock_bm)
        adapter.close()
        mock_bm.close.assert_called_once()


class TestPWIOIRefreshAndStaleAttendance:
    """Audit & verify delayed/stale attendance refresh handling in PWIOIPortalAdapter."""

    TARGET_DATE = date(2026, 8, 4)

    def test_not_marked_refresh_becomes_present(self):
        """1. NOT MARKED -> refresh -> PRESENT."""
        cfg = PWIOIPortalConfig(max_retries=2, retry_delay_seconds=0.0)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        def locator_mock(sel):
            loc = MagicMock()
            if "details" in sel:
                loc.count.return_value = 1
            elif "Back" in sel:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock

        from app.adapters.pwioi.aggregator import PWIOIPeriodRecord
        initial_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "NOT MARKED", AttendanceStatus.UNKNOWN, False)
        ]
        refreshed_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "PRESENT", AttendanceStatus.PRESENT, True)
        ]

        adapter._parse_period_rows = MagicMock(side_effect=[initial_periods, refreshed_periods])

        course_info = {"code": "302OPS", "name": "Operating System", "index": 0}
        periods, retries = adapter._extract_daily_records_for_course(mock_page, course_info, self.TARGET_DATE)

        assert retries == 1
        assert len(periods) == 1
        assert periods[0].status == AttendanceStatus.PRESENT
        assert periods[0].is_reliable is True
        mock_page.reload.assert_called_once()

        sub_att = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, periods, retries_attempted=retries)
        assert sub_att.status == AttendanceStatus.PRESENT
        assert sub_att.is_reliable is True
        assert sub_att.metadata["retries_attempted"] == 1
        assert sub_att.metadata["refreshed"] is True

    def test_not_marked_refresh_becomes_absent(self):
        """2. NOT MARKED -> refresh -> ABSENT."""
        cfg = PWIOIPortalConfig(max_retries=2, retry_delay_seconds=0.0)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        def locator_mock(sel):
            loc = MagicMock()
            if "details" in sel:
                loc.count.return_value = 1
            elif "Back" in sel:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock

        from app.adapters.pwioi.aggregator import PWIOIPeriodRecord
        initial_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "NOT MARKED", AttendanceStatus.UNKNOWN, False)
        ]
        refreshed_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "ABSENT", AttendanceStatus.ABSENT, True)
        ]

        adapter._parse_period_rows = MagicMock(side_effect=[initial_periods, refreshed_periods])

        course_info = {"code": "302OPS", "name": "Operating System", "index": 0}
        periods, retries = adapter._extract_daily_records_for_course(mock_page, course_info, self.TARGET_DATE)

        assert retries == 1
        assert len(periods) == 1
        assert periods[0].status == AttendanceStatus.ABSENT
        assert periods[0].is_reliable is True
        mock_page.reload.assert_called_once()

        sub_att = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, periods, retries_attempted=retries)
        assert sub_att.status == AttendanceStatus.ABSENT
        assert sub_att.is_reliable is True
        assert sub_att.metadata["retries_attempted"] == 1
        assert sub_att.metadata["refreshed"] is True

    def test_not_marked_all_retries_exhausted(self):
        """3. NOT MARKED -> all retries exhausted -> UNKNOWN + is_reliable=False."""
        cfg = PWIOIPortalConfig(max_retries=3, retry_delay_seconds=0.0)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        def locator_mock(sel):
            loc = MagicMock()
            if "details" in sel:
                loc.count.return_value = 1
            elif "Back" in sel:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock

        from app.adapters.pwioi.aggregator import PWIOIPeriodRecord
        stale_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "NOT MARKED", AttendanceStatus.UNKNOWN, False)
        ]

        adapter._parse_period_rows = MagicMock(return_value=stale_periods)

        course_info = {"code": "302OPS", "name": "Operating System", "index": 0}
        periods, retries = adapter._extract_daily_records_for_course(mock_page, course_info, self.TARGET_DATE)

        assert retries == 3
        assert mock_page.reload.call_count == 3
        assert len(periods) == 1
        assert periods[0].status == AttendanceStatus.UNKNOWN
        assert periods[0].is_reliable is False

        sub_att = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, periods, retries_attempted=retries)
        assert sub_att.status == AttendanceStatus.UNKNOWN
        assert sub_att.is_reliable is False
        assert sub_att.status != AttendanceStatus.ABSENT
        assert sub_att.metadata["retries_attempted"] == 3

    def test_missing_record_refresh_record_appears(self):
        """4. Missing record -> refresh -> record appears."""
        cfg = PWIOIPortalConfig(max_retries=2, retry_delay_seconds=0.0)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        def locator_mock(sel):
            loc = MagicMock()
            if "details" in sel:
                loc.count.return_value = 1
            elif "Back" in sel:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock

        from app.adapters.pwioi.aggregator import PWIOIPeriodRecord
        refreshed_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "PRESENT", AttendanceStatus.PRESENT, True)
        ]

        adapter._parse_period_rows = MagicMock(side_effect=[[], refreshed_periods])

        course_info = {"code": "302OPS", "name": "Operating System", "index": 0}
        periods, retries = adapter._extract_daily_records_for_course(mock_page, course_info, self.TARGET_DATE)

        assert retries == 1
        assert len(periods) == 1
        assert periods[0].status == AttendanceStatus.PRESENT
        assert periods[0].is_reliable is True
        mock_page.reload.assert_called_once()

    def test_stale_incomplete_data_refresh_valid_data(self):
        """5. Stale/incomplete data -> refresh -> valid data."""
        cfg = PWIOIPortalConfig(max_retries=2, retry_delay_seconds=0.0)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_bm.get_page.return_value = mock_page

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        def locator_mock(sel):
            loc = MagicMock()
            if "details" in sel:
                loc.count.return_value = 1
            elif "Back" in sel:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock

        from app.adapters.pwioi.aggregator import PWIOIPeriodRecord
        initial_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "Pending Verification", AttendanceStatus.UNKNOWN, False)
        ]
        refreshed_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "ABSENT", AttendanceStatus.ABSENT, True)
        ]

        adapter._parse_period_rows = MagicMock(side_effect=[initial_periods, refreshed_periods])

        course_info = {"code": "302OPS", "name": "Operating System", "index": 0}
        periods, retries = adapter._extract_daily_records_for_course(mock_page, course_info, self.TARGET_DATE)

        assert retries == 1
        assert len(periods) == 1
        assert periods[0].status == AttendanceStatus.ABSENT
        assert periods[0].is_reliable is True
        mock_page.reload.assert_called_once()

    def test_refresh_timeout_failure_fails_closed_safely(self):
        """6. Refresh/timeout failure -> fails closed safely without unhandled crash."""
        cfg = PWIOIPortalConfig(max_retries=2, retry_delay_seconds=0.0)
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_bm.get_page.return_value = mock_page
        mock_page.reload.side_effect = Exception("net::ERR_TIMED_OUT: Page reload timed out")

        adapter = PWIOIPortalAdapter(config=cfg, browser_manager=mock_bm)
        adapter._is_authenticated = True

        def locator_mock(sel):
            loc = MagicMock()
            if "details" in sel:
                loc.count.return_value = 1
            elif "Back" in sel:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock

        from app.adapters.pwioi.aggregator import PWIOIPeriodRecord
        initial_periods = [
            PWIOIPeriodRecord("period 1", self.TARGET_DATE, "NOT MARKED", AttendanceStatus.UNKNOWN, False)
        ]

        adapter._parse_period_rows = MagicMock(return_value=initial_periods)

        course_info = {"code": "302OPS", "name": "Operating System", "index": 0}
        periods, retries = adapter._extract_daily_records_for_course(mock_page, course_info, self.TARGET_DATE)

        assert retries == 1
        assert len(periods) == 1
        assert periods[0].status == AttendanceStatus.UNKNOWN
        assert periods[0].is_reliable is False

        sub_att = PWIOIPeriodAggregator.aggregate("302OPS", "Operating System", self.TARGET_DATE, periods, retries_attempted=retries)
        assert sub_att.status == AttendanceStatus.UNKNOWN
        assert sub_att.is_reliable is False

    def test_real_pwioi_dom_course_and_period_extraction(self):
        """End-to-end verification of course discovery, modal navigation, and period extraction on real DOM."""
        from playwright.sync_api import sync_playwright

        html = """<!DOCTYPE html>
<html>
<body>
<div class="xl:col-span-3 space-y-4 border border-gray-400 p-4 rounded-sm">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-gray-900">Course Breakdown</h2>
    <span class="text-sm text-gray-500">2 courses</span>
  </div>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
    <div class="bg-white border border-gray-400 rounded-sm shadow-sm p-4 hover:shadow-md transition-shadow cursor-pointer group" id="card-0">
      <div class="flex justify-between items-start mb-4">
        <div class="flex-1 min-w-0">
          <h4 class="font-semibold text-gray-900 text-sm mb-1 truncate">Operating System</h4>
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-gray-100 text-gray-700">302OPS</span>
            <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-green-50 text-green-700 border border-green-200">85.7%</span>
          </div>
        </div>
      </div>
      <div class="mt-3 pt-3 border-t border-gray-300">
        <p class="text-xs text-gray-500 text-center group-hover:text-slate-900 transition-colors">Click to view details &rarr;</p>
      </div>
    </div>
    <div class="bg-white border border-gray-400 rounded-sm shadow-sm p-4 hover:shadow-md transition-shadow cursor-pointer group" id="card-1">
      <div class="flex justify-between items-start mb-4">
        <div class="flex-1 min-w-0">
          <h4 class="font-semibold text-gray-900 text-sm mb-1 truncate">OJT / Java Web Developer (Spring Boot)</h4>
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-gray-100 text-gray-700">306JWD</span>
            <span class="px-2 py-0.5 rounded-sm text-xs font-medium bg-green-50 text-green-700 border border-green-200">90.0%</span>
          </div>
        </div>
      </div>
      <div class="mt-3 pt-3 border-t border-gray-300">
        <p class="text-xs text-gray-500 text-center group-hover:text-slate-900 transition-colors">Click to view details &rarr;</p>
      </div>
    </div>
  </div>
</div>
<div id="modal-root"></div>
<script>
document.querySelectorAll('.group').forEach((card, idx) => {
  card.addEventListener('click', () => {
    const courseCode = idx === 0 ? '302OPS' : '306JWD';
    const courseName = idx === 0 ? 'Operating System' : 'OJT / Java Web Developer (Spring Boot)';
    document.getElementById('modal-root').innerHTML = `
      <div class="fixed inset-0 bg-black/25 backdrop-blur-sm flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-lg max-w-4xl w-full max-h-[90vh] border border-slate-900 overflow-hidden shadow-2xl">
          <div class="bg-[#12294c] p-4 text-white">
            <div class="flex justify-between items-start">
              <div>
                <h3 class="text-lg font-semibold mb-2">${courseName}</h3>
                <div class="flex items-center gap-3">
                  <span class="bg-white/20 px-2 py-1 rounded-md text-xs font-medium">${courseCode}</span>
                </div>
              </div>
              <button class="p-1.5 hover:bg-white/20 rounded-md transition-colors cursor-pointer" id="close-btn" onclick="document.getElementById('modal-root').innerHTML=''">
                <svg class="w-5 h-5"><path d="M18 6L6 18M6 6l12 12"/></svg>
              </button>
            </div>
          </div>
          <div class="p-4 overflow-y-auto max-h-[calc(90vh-100px)]">
            <div class="flex flex-wrap gap-2 mb-6">
              <button class="px-4 py-2 rounded-sm text-sm font-medium transition-all cursor-pointer bg-gray-100 text-gray-700 hover:bg-gray-200" id="monthly-tab">Monthly Overview</button>
              <button class="px-4 py-2 rounded-sm text-sm font-medium transition-all cursor-pointer bg-[#12294c] text-white shadow-lg" id="daily-tab" onclick="showDaily()">Daily Records</button>
            </div>
            <div id="tab-content"></div>
          </div>
        </div>
      </div>
    `;
  });
});

function showDaily() {
  document.getElementById('tab-content').innerHTML = `
    <div class="space-y-4">
      <div class="bg-gray-50 rounded-sm p-4 border border-gray-200">
        <input type="text" placeholder="Search by date..." class="w-full pl-10 pr-3 py-2 text-sm border border-gray-300 rounded-sm bg-white" id="date-search" />
      </div>
      <div class="space-y-3" id="records-list">
        <div class="bg-white rounded-sm border border-gray-400 p-4">
          <div class="flex items-center justify-between">
            <div><p class="font-semibold text-gray-900 text-sm">Period 1</p></div>
            <div><span class="px-3 py-1 rounded-sm text-xs font-medium bg-green-50 text-green-700 border border-green-200">Present</span></div>
          </div>
        </div>
        <div class="bg-white rounded-sm border border-gray-400 p-4">
          <div class="flex items-center justify-between">
            <div><p class="font-semibold text-gray-900 text-sm">Period 2</p></div>
            <div><span class="px-3 py-1 rounded-sm text-xs font-medium bg-green-50 text-green-700 border border-green-200">Present</span></div>
          </div>
        </div>
      </div>
    </div>
  `;
}
</script>
</body>
</html>"""

        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            page = b.new_page()
            page.set_content(html)

            courses = adapter._enumerate_courses(page)
            assert len(courses) == 2
            assert courses[0]["code"] == "302OPS"
            assert courses[0]["name"] == "Operating System"
            assert courses[1]["code"] == "306JWD"
            assert courses[1]["name"] == "OJT / Java Web Developer (Spring Boot)"

            for c in courses:
                records, retries = adapter._extract_daily_records_for_course(page, c, self.TARGET_DATE)
                assert len(records) == 2
                assert records[0].period == "period 1"
                assert records[0].status == AttendanceStatus.PRESENT
                assert records[0].is_reliable is True
                assert records[1].period == "period 2"
                assert records[1].status == AttendanceStatus.PRESENT
                assert records[1].is_reliable is True

            b.close()

    def test_parse_period_rows_not_marked_underscore_normalizes_to_unknown(self):
        """Verifies that 'Not_marked' status badge normalizes to AttendanceStatus.UNKNOWN with reliable=False."""
        cfg = PWIOIPortalConfig()
        adapter = PWIOIPortalAdapter(config=cfg)

        mock_page = MagicMock()
        row = MagicMock()
        row.inner_text.return_value = "Period 1\nNot_marked"

        rows_loc = MagicMock()
        rows_loc.count.return_value = 1
        rows_loc.nth.return_value = row

        mock_page.locator.return_value = rows_loc

        periods = adapter._parse_period_rows(mock_page, self.TARGET_DATE)
        assert len(periods) == 1
        assert periods[0].period == "period 1"
        assert periods[0].status == AttendanceStatus.UNKNOWN
        assert periods[0].is_reliable is False

