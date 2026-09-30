"""Portal adapter factory and registry.

Decouples core application logic from specific college portal adapters.
"""

import logging
from typing import Any, Callable, Dict, Optional, Type

from app.adapters.base.adapter import BasePortalAdapter, PortalConfigurationError
from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario
from app.adapters.playwright.adapter import GenericPlaywrightPortalAdapter
from app.adapters.playwright.config import PlaywrightPortalConfig
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Registry mapping adapter identifiers to adapter factory callables
_ADAPTER_REGISTRY: Dict[str, Callable[..., BasePortalAdapter]] = {}


def register_adapter(name: str, factory_or_class: Any) -> None:
    """Register a new portal adapter implementation."""
    key = name.strip().lower()
    _ADAPTER_REGISTRY[key] = factory_or_class
    logger.info("Registered portal adapter: '%s'", key)


def get_portal_adapter(
    adapter_name: Optional[str] = None,
    settings: Optional[Settings] = None,
    scenario: Optional[str] = None,
    **kwargs: Any,
) -> BasePortalAdapter:
    """Instantiate the configured portal adapter.

    Priority:
    1. Explicit scenario parameter -> returns FakePortalAdapter(scenario=scenario)
    2. Explicit adapter_name argument
    3. settings.portal_adapter from environment (defaults to 'fake')

    Raises:
        PortalConfigurationError: If requested adapter is not registered.
    """
    app_settings = settings or get_settings()

    # If a fake scenario is explicitly requested (e.g. in test or simulation run), use fake adapter
    if scenario is not None:
        return FakePortalAdapter(scenario=scenario)

    resolved_name = (adapter_name or app_settings.portal_adapter or "fake").strip().lower()

    if resolved_name in ("fake", "mock", "test"):
        fake_scenario = scenario or FakeScenario.PYTHON_ABSENT
        return FakePortalAdapter(scenario=fake_scenario)

    if resolved_name in ("playwright", "generic_playwright", "generic"):
        config = PlaywrightPortalConfig(
            portal_url=app_settings.portal_url,
            username=app_settings.portal_username,
            password=app_settings.portal_password,
            auth_mode=app_settings.portal_auth_mode,
            storage_state_path=getattr(app_settings, "portal_storage_state", "storage_state/portal_session.json"),
            headless=getattr(app_settings, "portal_headless", True),
            timeout_ms=getattr(app_settings, "portal_timeout_ms", 15000),
            browser_channel=getattr(app_settings, "portal_browser_channel", None),
        )
        return GenericPlaywrightPortalAdapter(config=config, **kwargs)

    if resolved_name == "pwioi":
        from app.adapters.pwioi.adapter import PWIOIPortalAdapter
        from app.adapters.pwioi.config import PWIOIPortalConfig

        pwioi_browser_channel = (
            getattr(app_settings, "pwioi_browser_channel", None)
            or getattr(app_settings, "portal_browser_channel", None)
        )
        pwioi_config = PWIOIPortalConfig(
            portal_url=getattr(app_settings, "pwioi_portal_url", "https://app.pwioi.club/auth/student/login"),
            attendance_url=getattr(app_settings, "pwioi_attendance_url", "https://app.pwioi.club/dashboard/student/attendance"),
            academic_term=getattr(app_settings, "pwioi_academic_term", None),
            storage_state_path=getattr(app_settings, "pwioi_storage_state", "storage_state/pwioi_session.json"),
            headless=getattr(app_settings, "portal_headless", True),
            timeout_ms=getattr(app_settings, "portal_timeout_ms", 15000),
            browser_channel=pwioi_browser_channel,
            manual_login_timeout_ms=getattr(app_settings, "pwioi_manual_login_timeout_ms", 300000),
        )
        return PWIOIPortalAdapter(config=pwioi_config, **kwargs)

    # Check custom registry
    if resolved_name in _ADAPTER_REGISTRY:
        creator = _ADAPTER_REGISTRY[resolved_name]
        return creator(settings=app_settings, **kwargs)

    raise PortalConfigurationError(
        f"Unknown portal adapter '{resolved_name}'. "
        f"Available adapters: ['fake', 'playwright', 'generic_playwright'] + {list(_ADAPTER_REGISTRY.keys())}"
    )
