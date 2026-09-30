"""Playwright portal adapter package."""

from app.adapters.playwright.adapter import GenericPlaywrightPortalAdapter
from app.adapters.playwright.browser_manager import PlaywrightBrowserManager
from app.adapters.playwright.config import PlaywrightPortalConfig, PortalSelectors
from app.adapters.playwright.discovery import PortalDiscoveryService
from app.adapters.playwright.normalizer import AttendanceNormalizer

__all__ = [
    "AttendanceNormalizer",
    "GenericPlaywrightPortalAdapter",
    "PlaywrightBrowserManager",
    "PlaywrightPortalConfig",
    "PortalDiscoveryService",
    "PortalSelectors",
]
