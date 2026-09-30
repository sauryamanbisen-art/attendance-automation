"""Unit tests for PWIOIPortalConfig validation and security redaction."""

import pytest

from app.adapters.base.adapter import PortalConfigurationError
from app.adapters.pwioi.config import PWIOIPortalConfig, PWIOISelectors


class TestPWIOIPortalConfig:
    """Validate PWIOIPortalConfig validation and safety constraints."""

    def test_default_config_is_valid(self):
        cfg = PWIOIPortalConfig()
        assert cfg.portal_url == "https://app.pwioi.club/auth/student/login"
        assert cfg.attendance_url == "https://app.pwioi.club/dashboard/student/attendance"
        assert cfg.academic_term is None
        assert cfg.headless is True
        assert cfg.manual_login_timeout_ms == 300000
        assert cfg.validate() is True

    def test_validate_empty_portal_url_raises(self):
        cfg = PWIOIPortalConfig(portal_url="")
        with pytest.raises(PortalConfigurationError, match="portal_url must be configured"):
            cfg.validate()

    def test_validate_empty_attendance_url_raises(self):
        cfg = PWIOIPortalConfig(attendance_url="")
        with pytest.raises(PortalConfigurationError, match="attendance_url must be configured"):
            cfg.validate()

    def test_validate_invalid_url_scheme_raises(self):
        cfg = PWIOIPortalConfig(portal_url="not-a-url")
        with pytest.raises(PortalConfigurationError, match="Invalid portal_url"):
            cfg.validate()

    def test_validate_placeholder_url_fails_closed(self):
        cfg = PWIOIPortalConfig(portal_url="https://portal.example.edu")
        with pytest.raises(PortalConfigurationError, match="Cannot use placeholder URL"):
            cfg.validate()

    def test_safe_dict_contains_expected_keys(self):
        cfg = PWIOIPortalConfig(academic_term="3", browser_channel="chrome")
        safe = cfg.safe_dict()
        assert safe["portal_url"] == "https://app.pwioi.club/auth/student/login"
        assert safe["academic_term"] == "3"
        assert safe["headless"] is True
        assert safe["browser_channel"] == "chrome"

    def test_browser_channel_default_none_and_configurable(self):
        cfg_default = PWIOIPortalConfig()
        assert cfg_default.browser_channel is None

        cfg_chrome = PWIOIPortalConfig(browser_channel="chrome")
        assert cfg_chrome.browser_channel == "chrome"

    def test_selectors_have_expected_definitions(self):
        sel = PWIOISelectors()
        assert hasattr(sel, "no_records_indicator")
        assert "No Records Found" in sel.no_records_indicator
        assert "select" in sel.academic_term_dropdown
        assert "Click to view details" in sel.view_details_action
        assert "cursor-pointer" in sel.course_card
        assert "Daily Records" in sel.daily_records_tab

