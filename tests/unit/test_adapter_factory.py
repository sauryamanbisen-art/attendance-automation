"""Unit tests for portal adapter factory and registry."""

import pytest

from app.adapters.base.adapter import BasePortalAdapter, PortalConfigurationError
from app.adapters.factory import get_portal_adapter, register_adapter
from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario
from app.adapters.playwright.adapter import GenericPlaywrightPortalAdapter
from app.config import Settings


class MockCollegeAdapter(BasePortalAdapter):
    @property
    def adapter_name(self) -> str:
        return "custom_college"

    def validate_config(self) -> bool:
        return True

    def authenticate(self) -> bool:
        return True

    def get_attendance_for_date(self, target_date):
        return []

    def normalize_status(self, raw_status):
        return None

    def close(self):
        pass


def test_get_fake_adapter_by_name():
    adapter = get_portal_adapter(adapter_name="fake")
    assert isinstance(adapter, FakePortalAdapter)
    assert adapter.adapter_name == "fake"


def test_get_fake_adapter_by_scenario():
    adapter = get_portal_adapter(scenario="python_present")
    assert isinstance(adapter, FakePortalAdapter)
    assert adapter.scenario == FakeScenario.PYTHON_PRESENT


def test_get_playwright_adapter():
    settings = Settings(
        portal_adapter="playwright",
        portal_url="https://portal.university.edu",
        portal_username="alice",
        portal_browser_channel="chrome",
    )
    adapter = get_portal_adapter(settings=settings)
    assert isinstance(adapter, GenericPlaywrightPortalAdapter)
    assert adapter.adapter_name == "generic_playwright"
    assert adapter.config.portal_url == "https://portal.university.edu"
    assert adapter.config.browser_channel == "chrome"


def test_register_and_retrieve_custom_adapter():
    register_adapter("custom_college", lambda **kwargs: MockCollegeAdapter())
    adapter = get_portal_adapter(adapter_name="custom_college")
    assert isinstance(adapter, MockCollegeAdapter)
    assert adapter.adapter_name == "custom_college"


def test_get_pwioi_adapter():
    from app.adapters.pwioi.adapter import PWIOIPortalAdapter
    adapter = get_portal_adapter(adapter_name="pwioi")
    assert isinstance(adapter, PWIOIPortalAdapter)
    assert adapter.adapter_name == "pwioi"
    assert adapter.is_read_only is True


def test_get_pwioi_adapter_with_browser_channel():
    from app.adapters.pwioi.adapter import PWIOIPortalAdapter
    settings = Settings(
        portal_adapter="pwioi",
        pwioi_browser_channel="chrome",
    )
    adapter = get_portal_adapter(adapter_name="pwioi", settings=settings)
    assert isinstance(adapter, PWIOIPortalAdapter)
    assert adapter.config.browser_channel == "chrome"
    assert adapter.browser_manager.browser_channel == "chrome"


def test_unknown_adapter_raises_configuration_error():
    with pytest.raises(PortalConfigurationError, match="Unknown portal adapter 'non_existent_portal'"):
        get_portal_adapter(adapter_name="non_existent_portal")
