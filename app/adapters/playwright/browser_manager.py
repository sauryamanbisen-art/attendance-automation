"""Playwright browser lifecycle and isolated session context manager.

Safety Invariants:
- Isolated browser contexts for all operations.
- Headless by default, headed mode supported for manual interactive setup.
- Storage state files saved with restricted POSIX 0600 permissions.
- Reliable cleanup of browser, context, and Playwright instances.
"""

import json
import logging
import os
import stat
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PlaywrightBrowserManager:
    """Manages Playwright initialization, isolated browser contexts, and clean teardown."""

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 15000,
        playwright_instance: Optional[Any] = None,
        browser_instance: Optional[Any] = None,
        browser_channel: Optional[str] = None,
        storage_state_path: Optional[str] = None,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.browser_channel = browser_channel
        self.storage_state_path = storage_state_path
        self._playwright = playwright_instance
        self._browser = browser_instance
        self._context: Optional[Any] = None
        self._page: Optional[Any] = None
        self._pending_session_storage: Optional[dict[str, Any]] = None
        self._is_external_playwright = playwright_instance is not None

    def _ensure_browser(self) -> Any:
        """Initialize Playwright and launch Chromium if not already active."""
        if self._browser is not None:
            return self._browser

        if self._playwright is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()

        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": ["--no-sandbox", "--disable-dev-shm-usage"],
        }
        if self.browser_channel:
            launch_kwargs["channel"] = self.browser_channel

        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        return self._browser

    def get_context(self, storage_state_path: Optional[str] = None) -> Any:
        """Create or return an isolated browser context."""
        if self._context is not None:
            return self._context

        browser = self._ensure_browser()

        context_options: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        }

        effective_storage_path = storage_state_path or self.storage_state_path
        # If a saved session file exists and is readable, restore it
        if effective_storage_path and os.path.exists(effective_storage_path):
            try:
                context_options["storage_state"] = effective_storage_path
                logger.info("Restoring saved browser session state from %s (loaded=True)", effective_storage_path)
                try:
                    with open(effective_storage_path, "r", encoding="utf-8") as f:
                        saved_data = json.load(f)
                        self._pending_session_storage = saved_data.get("sessionStorage", {})
                except Exception as read_exc:
                    logger.debug("Could not read custom storage keys from %s: %s", effective_storage_path, read_exc)
            except Exception as exc:
                logger.warning("Could not load storage state from %s: %s", effective_storage_path, exc)
        else:
            logger.info("No existing storage state file found at %s (loaded=False). Starting fresh session.", effective_storage_path)

        self._context = browser.new_context(**context_options)
        self._context.set_default_timeout(self.timeout_ms)
        self._context.set_default_navigation_timeout(self.timeout_ms)
        return self._context

    def get_page(self, storage_state_path: Optional[str] = None) -> Any:
        """Create or return an active page inside the isolated context."""
        if self._page is not None and not self._page.is_closed():
            return self._page

        context = self.get_context(storage_state_path=storage_state_path)
        self._page = context.new_page()

        if self._pending_session_storage:
            try:
                storage_json = json.dumps(self._pending_session_storage)
                init_script = (
                    "(() => {"
                    f"  try {{ const data = {storage_json};"
                    "    for (const [k, v] of Object.entries(data)) {"
                    "      if (sessionStorage.getItem(k) === null) { sessionStorage.setItem(k, v); }"
                    "    }"
                    "  } catch (e) {}"
                    "})();"
                )
                self._page.add_init_script(init_script)
            except Exception as exc:
                logger.debug("Could not register sessionStorage init script: %s", exc)

        return self._page

    def save_storage_state(self, path: Optional[str] = None) -> None:
        """Persist current session cookies, localStorage, and sessionStorage with 0600 permissions."""
        effective_path = path or self.storage_state_path
        if not effective_path or self._context is None:
            return

        abs_path = os.path.abspath(effective_path)
        parent_dir = os.path.dirname(abs_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        temp_path = f"{abs_path}.tmp"
        try:
            self._context.storage_state(path=temp_path)

            # Capture sessionStorage from active page if available
            if self._page is not None and not self._page.is_closed():
                try:
                    session_storage = self._page.evaluate(
                        "() => { const s = {}; for (let i = 0; i < sessionStorage.length; i++) { const k = sessionStorage.key(i); s[k] = sessionStorage.getItem(k); } return s; }"
                    )
                    if session_storage and os.path.exists(temp_path):
                        with open(temp_path, "r+", encoding="utf-8") as f:
                            data = json.load(f)
                            data["sessionStorage"] = session_storage
                            f.seek(0)
                            json.dump(data, f, indent=2)
                            f.truncate()
                except Exception as ss_exc:
                    logger.debug("Could not capture sessionStorage: %s", ss_exc)

            # Set 0600 permissions (user read/write only)
            try:
                os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

            os.replace(temp_path, abs_path)
            persist_time = datetime.now(timezone.utc).isoformat()
            logger.info("Saved refreshed browser session storage state to %s (timestamp=%s, persisted=True)", abs_path, persist_time)
        except Exception as exc:
            logger.error("Failed to save storage state to %s: %s", abs_path, exc)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def close(self) -> None:
        """Reliably close page, context, browser, and stop Playwright."""
        if self._page is not None:
            try:
                self._page.close()
            except Exception as exc:
                logger.debug("Error closing page: %s", exc)
            finally:
                self._page = None

        if self._context is not None:
            try:
                self._context.close()
            except Exception as exc:
                logger.debug("Error closing context: %s", exc)
            finally:
                self._context = None

        if self._browser is not None and not self._is_external_playwright:
            try:
                self._browser.close()
            except Exception as exc:
                logger.debug("Error closing browser: %s", exc)
            finally:
                self._browser = None

        if self._playwright is not None and not self._is_external_playwright:
            try:
                self._playwright.stop()
            except Exception as exc:
                logger.debug("Error stopping Playwright: %s", exc)
            finally:
                self._playwright = None

    def __enter__(self) -> "PlaywrightBrowserManager":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
