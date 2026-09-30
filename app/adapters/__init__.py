from app.adapters.base.adapter import (
    BasePortalAdapter,
    PortalAdapterError,
    PortalAuthenticationError,
    PortalConfigurationError,
    PortalParsingError,
    PortalUnavailableError,
    SubjectAttendance,
)
from app.adapters.factory import get_portal_adapter, register_adapter
from app.adapters.fake.adapter import FakePortalAdapter, FakeScenario
from app.adapters.playwright import (
    AttendanceNormalizer,
    GenericPlaywrightPortalAdapter,
    PlaywrightBrowserManager,
    PlaywrightPortalConfig,
    PortalDiscoveryService,
    PortalSelectors,
)
from app.adapters.pwioi import (
    PWIOIPeriodAggregator,
    PWIOIPeriodRecord,
    PWIOIPortalAdapter,
    PWIOIPortalConfig,
    PWIOISelectors,
)

__all__ = [
    "AttendanceNormalizer",
    "BasePortalAdapter",
    "FakePortalAdapter",
    "FakeScenario",
    "GenericPlaywrightPortalAdapter",
    "PlaywrightBrowserManager",
    "PlaywrightPortalConfig",
    "PortalAdapterError",
    "PortalAuthenticationError",
    "PortalConfigurationError",
    "PortalDiscoveryService",
    "PortalParsingError",
    "PortalSelectors",
    "PortalUnavailableError",
    "PWIOIPeriodAggregator",
    "PWIOIPeriodRecord",
    "PWIOIPortalAdapter",
    "PWIOIPortalConfig",
    "PWIOISelectors",
    "SubjectAttendance",
    "get_portal_adapter",
    "register_adapter",
]
