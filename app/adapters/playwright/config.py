"""Configuration and selector definitions for Playwright portal adapters.

Safety Invariants:
- Never hardcodes passwords or sensitive tokens.
- Credentials masked in repr and safe_dict representations.
- Read-only operations only.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from app.adapters.base.adapter import PortalConfigurationError
from app.security.redaction import redact_string


@dataclass
class PortalSelectors:
    """CSS selectors used by the generic Playwright portal adapter.

    Configurable per college or discoverable via PortalDiscoveryService.
    """

    login_url: Optional[str] = None
    username_input: str = "input[type='text'], input[name*='user'], input[name*='email'], input[name*='login'], #username, #email"
    password_input: str = "input[type='password'], input[name*='pass'], #password"
    submit_button: str = "button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign In'), button:has-text('Log In')"
    mfa_indicator: str = "input[name*='otp'], input[name*='mfa'], input[name*='code'], :has-text('Verification Code'), :has-text('Enter OTP'), :has-text('Authenticator')"
    captcha_indicator: str = ".g-recaptcha, .h-captcha, iframe[src*='recaptcha'], iframe[src*='hcaptcha'], input[name*='captcha']"
    
    attendance_nav: Optional[str] = "a:has-text('Attendance'), a[href*='attendance']"
    attendance_url: Optional[str] = None
    attendance_table: str = "table.attendance, #attendance-table, table:has(th:has-text('Subject')), table:has(th:has-text('Course')), table"
    table_rows: str = "tbody tr"

    # Column index hints (-1 indicates auto-detection by header text)
    subject_code_col: int = -1
    subject_name_col: int = -1
    status_col: int = -1
    date_col: int = -1


@dataclass
class PlaywrightPortalConfig:
    """Immutable runtime configuration for Playwright portal adapter."""

    portal_url: str = "https://portal.example.edu"
    username: Optional[str] = "demo_student"
    password: Optional[str] = None
    auth_mode: str = "password"  # 'password', 'session_state', 'manual_interactive'
    storage_state_path: Optional[str] = "storage_state/portal_session.json"
    headless: bool = True
    timeout_ms: int = 15000
    browser_channel: Optional[str] = None
    wait_until: str = "domcontentloaded"
    selectors: PortalSelectors = field(default_factory=PortalSelectors)

    def validate(self) -> bool:
        """Validate configuration presence and URL format.

        Raises:
            PortalConfigurationError: If portal_url is missing, invalid, or placeholder.
        """
        if not self.portal_url or not self.portal_url.strip():
            raise PortalConfigurationError("Portal URL is not configured.")

        parsed = urlparse(self.portal_url.strip())
        if not parsed.scheme or not parsed.netloc:
            raise PortalConfigurationError(f"Invalid portal URL: '{self.portal_url}'. Must include http:// or https://.")

        if self.is_placeholder_url():
            raise PortalConfigurationError(
                f"Cannot use placeholder URL '{self.portal_url}'. Please configure a valid college portal URL."
            )

        if self.auth_mode == "password":
            if not self.username:
                raise PortalConfigurationError("Portal username is required for password authentication mode.")
            # Note: password may be None during dry-run / config checks, but needed for live login

        return True

    def is_placeholder_url(self) -> bool:
        """Check if configured URL is an unconfigured example placeholder."""
        return "portal.example.edu" in self.portal_url or "example.com" in self.portal_url

    def safe_dict(self) -> dict[str, Any]:
        """Return dictionary representation with passwords and secrets masked."""
        return {
            "portal_url": self.portal_url,
            "username": self.username,
            "password": "[REDACTED]" if self.password else None,
            "auth_mode": self.auth_mode,
            "storage_state_path": self.storage_state_path,
            "headless": self.headless,
            "timeout_ms": self.timeout_ms,
            "browser_channel": self.browser_channel,
            "is_placeholder_url": self.is_placeholder_url(),
        }

    def __repr__(self) -> str:
        pwd_repr = "[REDACTED]" if self.password else "None"
        return (
            f"PlaywrightPortalConfig(portal_url={self.portal_url!r}, "
            f"username={self.username!r}, password={pwd_repr}, "
            f"auth_mode={self.auth_mode!r}, headless={self.headless})"
        )
