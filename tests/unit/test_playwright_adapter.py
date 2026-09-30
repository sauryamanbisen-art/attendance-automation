"""Comprehensive unit tests for the Playwright portal adapter, browser manager, and discovery."""

import os
import stat
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.base.adapter import (
    PortalAuthenticationError,
    PortalConfigurationError,
    PortalUnavailableError,
)
from app.adapters.playwright.adapter import GenericPlaywrightPortalAdapter
from app.adapters.playwright.browser_manager import PlaywrightBrowserManager
from app.adapters.playwright.config import PlaywrightPortalConfig, PortalSelectors
from app.adapters.playwright.discovery import PortalDiscoveryService
from app.core.enums import AttendanceStatus


# ═══════════════════════════════════════════════════════════════════════════
# 1. PlaywrightPortalConfig Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPlaywrightPortalConfig:
    def test_default_config(self):
        cfg = PlaywrightPortalConfig()
        assert cfg.portal_url == "https://portal.example.edu"
        assert cfg.is_placeholder_url() is True
        assert cfg.headless is True
        assert cfg.timeout_ms == 15000

    def test_validate_valid_config(self):
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.mit.edu",
            username="alice",
            password="secret_password_123",
        )
        assert cfg.validate() is True
        assert cfg.is_placeholder_url() is False

    def test_validate_missing_url_raises(self):
        with pytest.raises(PortalConfigurationError, match="Portal URL is not configured"):
            PlaywrightPortalConfig(portal_url="").validate()

    def test_validate_invalid_url_scheme_raises(self):
        with pytest.raises(PortalConfigurationError, match="Invalid portal URL"):
            PlaywrightPortalConfig(portal_url="not_a_valid_url").validate()

    def test_validate_missing_username_in_password_mode_raises(self):
        with pytest.raises(PortalConfigurationError, match="Portal username is required"):
            PlaywrightPortalConfig(portal_url="https://portal.univ.edu", username=None, auth_mode="password").validate()

    def test_safe_dict_redacts_password(self):
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu",
            username="alice",
            password="super_secret_portal_password",
        )
        data = cfg.safe_dict()
        assert data["username"] == "alice"
        assert data["password"] == "[REDACTED]"
        assert "super_secret_portal_password" not in str(data)

    def test_repr_redacts_password(self):
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu",
            username="alice",
            password="super_secret_portal_password",
        )
        repr_str = repr(cfg)
        assert "super_secret_portal_password" not in repr_str
        assert "[REDACTED]" in repr_str


# ═══════════════════════════════════════════════════════════════════════════
# 2. PlaywrightBrowserManager Lifecycle & Session Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPlaywrightBrowserManager:
    def test_save_storage_state_sets_0600_permissions(self, tmp_path):
        state_file = str(tmp_path / "sessions" / "test_session.json")

        mock_context = MagicMock()

        def fake_storage_state(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"cookies": [], "origins": []}')

        mock_context.storage_state.side_effect = fake_storage_state

        manager = PlaywrightBrowserManager()
        manager._context = mock_context

        manager.save_storage_state(state_file)

        assert os.path.exists(state_file)
        mode = os.stat(state_file).st_mode
        assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0  # No group or world permissions

    def test_close_cleans_up_all_resources_safely(self):
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_browser = MagicMock()
        mock_playwright = MagicMock()

        manager = PlaywrightBrowserManager()
        manager._page = mock_page
        manager._context = mock_context
        manager._browser = mock_browser
        manager._playwright = mock_playwright

        manager.close()

        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()

        assert manager._page is None
        assert manager._context is None
        assert manager._browser is None
        assert manager._playwright is None

    def test_close_handles_exceptions_during_teardown_gracefully(self):
        mock_page = MagicMock()
        mock_page.close.side_effect = Exception("Page already detached")

        manager = PlaywrightBrowserManager()
        manager._page = mock_page

        # Must not raise
        manager.close()
        assert manager._page is None

    def test_ensure_browser_launches_without_channel_by_default(self):
        mock_playwright = MagicMock()
        mock_browser = MagicMock()
        mock_playwright.chromium.launch.return_value = mock_browser

        manager = PlaywrightBrowserManager(playwright_instance=mock_playwright, headless=True)
        browser = manager._ensure_browser()

        assert browser is mock_browser
        mock_playwright.chromium.launch.assert_called_once_with(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    def test_ensure_browser_launches_with_custom_channel(self):
        mock_playwright = MagicMock()
        mock_browser = MagicMock()
        mock_playwright.chromium.launch.return_value = mock_browser

        manager = PlaywrightBrowserManager(
            playwright_instance=mock_playwright,
            headless=False,
            browser_channel="chrome",
        )
        browser = manager._ensure_browser()

        assert browser is mock_browser
        mock_playwright.chromium.launch.assert_called_once_with(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            channel="chrome",
        )

    def test_generic_adapter_propagates_browser_channel(self):
        cfg = PlaywrightPortalConfig(portal_url="https://example.edu/portal", browser_channel="chrome")
        adapter = GenericPlaywrightPortalAdapter(config=cfg)
        assert adapter.browser_manager.browser_channel == "chrome"


# ═══════════════════════════════════════════════════════════════════════════
# 3. PortalDiscoveryService Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPortalDiscoveryService:
    def test_inspect_page_unreachable(self):
        discovery = PortalDiscoveryService()
        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("Connection refused")

        result = discovery.inspect_page(mock_page, "https://offline-portal.edu")
        assert result["reachable"] is False
        assert "Connection refused" in result["error"]

    def test_inspect_login_page_detects_mfa_and_captcha(self):
        discovery = PortalDiscoveryService()
        mock_page = MagicMock()
        mock_page.title.return_value = "University Login"
        mock_page.url = "https://portal.univ.edu/login"

        def mock_locator(selector):
            loc = MagicMock()
            if "otp" in selector or "mfa" in selector:
                loc.count.return_value = 1  # MFA present
            elif "recaptcha" in selector or "captcha" in selector:
                loc.count.return_value = 1  # CAPTCHA present
            elif "user" in selector or "password" in selector or "submit" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = mock_locator

        result = discovery.inspect_page(mock_page, "https://portal.univ.edu/login")
        assert result["reachable"] is True
        assert result["is_login_page"] is True
        assert result["mfa_detected"] is True
        assert result["captcha_detected"] is True
        assert result["requires_interactive_auth"] is True

    def test_inspect_attendance_table(self):
        discovery = PortalDiscoveryService()
        mock_page = MagicMock()
        mock_page.title.return_value = "Attendance Portal"
        mock_page.url = "https://portal.univ.edu/attendance"

        table_loc = MagicMock()
        table_loc.count.return_value = 1
        headers_loc = MagicMock()
        headers_loc.all_inner_texts.return_value = ["Subject Code", "Subject Name", "Status"]
        table_loc.first.locator.return_value = headers_loc

        rows_loc = MagicMock()
        rows_loc.count.return_value = 4

        def mock_locator(selector):
            if "table" in selector and "tr" not in selector:
                return table_loc
            if "tbody tr" in selector:
                return rows_loc
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = mock_locator

        result = discovery.inspect_page(mock_page, "https://portal.univ.edu/attendance")
        assert result["has_attendance_table"] is True
        assert result["table_rows_count"] == 4
        assert result["table_headers"] == ["Subject Code", "Subject Name", "Status"]


# ═══════════════════════════════════════════════════════════════════════════
# 4. GenericPlaywrightPortalAdapter Authentication & Attendance Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGenericPlaywrightPortalAdapter:
    def test_placeholder_url_fails_closed(self):
        adapter = GenericPlaywrightPortalAdapter(
            config=PlaywrightPortalConfig(portal_url="https://portal.example.edu")
        )
        with pytest.raises(PortalConfigurationError, match="placeholder URL"):
            adapter.authenticate()

        with pytest.raises(PortalConfigurationError, match="placeholder URL"):
            adapter.get_attendance_for_date(date(2026, 9, 27))

    def test_authenticate_existing_session_valid(self):
        """If page does not show login inputs, session is already valid."""
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu/dashboard",
            username="student1",
            password="pwd",
        )
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()

        # No username or password inputs found -> user is already authenticated
        mock_loc = MagicMock()
        mock_loc.count.return_value = 0
        mock_page.locator.return_value = mock_loc

        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        assert adapter.authenticate() is True

    def test_authenticate_captcha_raises_auth_error(self):
        """CRITICAL: CAPTCHA detected must raise PortalAuthenticationError without bypassing."""
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu/login",
            username="student1",
            password="pwd",
        )
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()

        def locator_side_effect(sel):
            loc = MagicMock()
            if "captcha" in sel:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 1
            return loc

        mock_page.locator.side_effect = locator_side_effect
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        with pytest.raises(PortalAuthenticationError, match="CAPTCHA verification"):
            adapter.authenticate()

    def test_authenticate_mfa_raises_auth_error(self):
        """CRITICAL: MFA detected must raise PortalAuthenticationError without bypassing."""
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu/login",
            username="student1",
            password="pwd",
        )
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()

        def locator_side_effect(sel):
            loc = MagicMock()
            if "otp" in sel or "mfa" in sel:
                loc.count.return_value = 1
            elif "captcha" in sel:
                loc.count.return_value = 0
            else:
                loc.count.return_value = 1
            return loc

        mock_page.locator.side_effect = locator_side_effect
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        with pytest.raises(PortalAuthenticationError, match="Multi-Factor Authentication"):
            adapter.authenticate()

    def test_authenticate_missing_password_raises(self):
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu/login",
            username="student1",
            password=None,  # Missing password
        )
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()

        def mock_locator(sel):
            loc = MagicMock()
            if "captcha" in sel or "mfa" in sel or "otp" in sel:
                loc.count.return_value = 0
            else:
                loc.count.return_value = 1
            return loc

        mock_page.locator.side_effect = mock_locator
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        with pytest.raises(PortalAuthenticationError, match="password is not configured"):
            adapter.authenticate()

    def test_authenticate_rejected_credentials_raises(self):
        """Login failure (password input remains on page post-submit) raises PortalAuthenticationError."""
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu/login",
            username="student1",
            password="wrong_password",
        )
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()

        def mock_locator(sel):
            loc = MagicMock()
            if "captcha" in sel or "mfa" in sel or "otp" in sel:
                loc.count.return_value = 0
            else:
                loc.count.return_value = 1
            return loc

        mock_page.locator.side_effect = mock_locator
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        with pytest.raises(PortalAuthenticationError, match="rejected login credentials"):
            adapter.authenticate()

    def test_authenticate_success(self, tmp_path):
        state_file = str(tmp_path / "session.json")
        cfg = PlaywrightPortalConfig(
            portal_url="https://portal.univ.edu/login",
            username="student1",
            password="correct_password",
            storage_state_path=state_file,
        )
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()

        # Initial check: inputs present; post-submit check: inputs gone
        call_count = {"user": 0, "pass": 0, "captcha": 0, "mfa": 0}

        def mock_locator(sel):
            loc = MagicMock()
            if "captcha" in sel:
                loc.count.return_value = 0
            elif "mfa" in sel:
                loc.count.return_value = 0
            elif "user" in sel:
                loc.count.return_value = 1
            elif "pass" in sel:
                call_count["pass"] += 1
                # First check on login screen (1), post-submit check (0)
                loc.count.return_value = 1 if call_count["pass"] <= 1 else 0
            else:
                loc.count.return_value = 1
            return loc

        mock_page.locator.side_effect = mock_locator
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        assert adapter.authenticate() is True

        mock_page.fill.assert_any_call(cfg.selectors.username_input, "student1")
        mock_page.fill.assert_any_call(cfg.selectors.password_input, "correct_password")
        mock_page.click.assert_called_once_with(cfg.selectors.submit_button)
        mock_bm.save_storage_state.assert_called_once_with(state_file)

    def test_get_attendance_parses_multiple_subjects(self):
        """Verify parsing multiple rows into normalized domain SubjectAttendance records."""
        cfg = PlaywrightPortalConfig(portal_url="https://portal.univ.edu/attendance")
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()

        # Table exists
        table_loc = MagicMock()
        table_loc.count.return_value = 1

        # 4 rows
        row1 = MagicMock()
        row1.locator.return_value.all_inner_texts.return_value = ["CS101", "Python Programming", "Present"]

        row2 = MagicMock()
        row2.locator.return_value.all_inner_texts.return_value = ["CS102", "Data Structures", "Absent"]

        row3 = MagicMock()
        row3.locator.return_value.all_inner_texts.return_value = ["CS103", "Algorithms", "Duty Leave"]

        row4 = MagicMock()
        row4.locator.return_value.all_inner_texts.return_value = ["CS104", "Databases", "Absent (Provisional)"]

        rows_loc = MagicMock()
        rows_loc.count.return_value = 4
        rows_loc.nth.side_effect = lambda idx: [row1, row2, row3, row4][idx]

        def locator_mock(sel):
            if "table" in sel and "tr" not in sel:
                return table_loc
            if "tbody tr" in sel:
                return rows_loc
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        mock_page.locator.side_effect = locator_mock
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        records = adapter.get_attendance_for_date(date(2026, 9, 27))

        assert len(records) == 4

        # CS101: Present -> PRESENT, reliable=True
        assert records[0].subject_code == "CS101"
        assert records[0].status == AttendanceStatus.PRESENT
        assert records[0].is_reliable is True

        # CS102: Absent -> ABSENT, reliable=True
        assert records[1].subject_code == "CS102"
        assert records[1].status == AttendanceStatus.ABSENT
        assert records[1].is_reliable is True

        # CS103: Duty Leave -> UNKNOWN, reliable=False
        assert records[2].subject_code == "CS103"
        assert records[2].status == AttendanceStatus.UNKNOWN
        assert records[2].is_reliable is False

        # CS104: Absent (Provisional) -> UNKNOWN, reliable=False (ambiguous label fails closed)
        assert records[3].subject_code == "CS104"
        assert records[3].status == AttendanceStatus.UNKNOWN
        assert records[3].is_reliable is False

    def test_get_attendance_missing_table_returns_unknown(self):
        """When attendance table is missing on page, returns diagnostic UNKNOWN record."""
        cfg = PlaywrightPortalConfig(portal_url="https://portal.univ.edu/attendance")
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.url = "https://portal.univ.edu/attendance"

        table_loc = MagicMock()
        table_loc.count.return_value = 0  # Table not found

        mock_page.locator.return_value = table_loc
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        records = adapter.get_attendance_for_date(date(2026, 9, 27))

        assert len(records) == 1
        assert records[0].status == AttendanceStatus.UNKNOWN
        assert records[0].is_reliable is False
        assert "Attendance table not found" in records[0].metadata["error"]

    def test_get_attendance_network_error_raises_unavailable(self):
        """Page network failure raises PortalUnavailableError."""
        cfg = PlaywrightPortalConfig(portal_url="https://portal.univ.edu/attendance")
        mock_bm = MagicMock(spec=PlaywrightBrowserManager)
        mock_page = MagicMock()
        mock_page.locator.side_effect = Exception("net::ERR_CONNECTION_TIMED_OUT")
        mock_bm.get_page.return_value = mock_page

        adapter = GenericPlaywrightPortalAdapter(config=cfg, browser_manager=mock_bm)
        with pytest.raises(PortalUnavailableError, match="ERR_CONNECTION_TIMED_OUT"):
            adapter.get_attendance_for_date(date(2026, 9, 27))
