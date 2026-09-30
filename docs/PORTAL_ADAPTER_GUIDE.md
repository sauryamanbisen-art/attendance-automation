# Portal Adapter Architecture & Development Guide

This guide details the **Portal Adapter Framework** in Attendance Automation. It explains how browser automation is safely integrated, how attendance records are parsed and normalized, and how contributors can add adapters for specific college portals.

---

## 1. Architectural Overview

The portal integration layer is designed to be **modular**, **strictly read-only**, and **fail-closed**. College-specific portal logic is completely isolated from core business logic (the Decision Engine and notification dispatchers).

```text
+--------------------------------------------------------------------------+
|                        College Portal Interface Layer                    |
|                                                                          |
|  +--------------------------------------------------------------------+  |
|  |                        BasePortalAdapter                           |  |
|  |  - validate_config() -> bool                                       |  |
|  |  - authenticate() -> bool                                          |  |
|  |  - get_attendance_for_date(date) -> List[SubjectAttendance]        |  |
|  |  - normalize_status(raw) -> AttendanceStatus                       |  |
|  |  - close() -> None                                                 |  |
|  +--------------------------------------------------------------------+  |
|               ^                                       ^                  |
|               |                                       |                  |
|  +-------------------------+             +-------------------------+     |
|  |    FakePortalAdapter    |             | GenericPlaywrightAdapter|     |
|  |  (Deterministic mocks)  |             | (Playwright Headless)   |     |
|  +-------------------------+             +-------------------------+     |
|                                                       |                  |
|                                    +------------------+----------------+ |
|                                    |                  |                | |
|                                    v                  v                v |
|                             +------------+     +------------+     +----+ |
|                             |  Browser   |     | Normalizer |     | Disc |
|                             |  Manager   |     | & Safety   |     | overy|
|                             +------------+     +------------+     +----+ |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                  Core Business Logic (Portal-Agnostic)                   |
|                                                                          |
|  +--------------------+      +--------------------+      +-------------+ |
|  | Attendance Record  | ---> |   DecisionEngine   | ---> | Notification| |
|  | (ABSENT/PRESENT/   |      |  (Evaluates safety |      | (Dry-Run /  | |
|  |  UNKNOWN)          |      |     invariants)    |      |  GoogleChat)| |
|  +--------------------+      +--------------------+      +-------------+ |
+--------------------------------------------------------------------------+
```

---

## 2. Core Safety Invariants

The adapter framework enforces the following non-negotiable safety rules:

1. **Strictly Read-Only**: Adapters must **never** perform write operations, submit correction requests on the portal, or mark attendance.
2. **`UNKNOWN` Never Becomes `ABSENT`**: Missing rows, missing tables, unexpected status text, or parse failures always evaluate to `AttendanceStatus.UNKNOWN` with `is_reliable = False`.
3. **Explicit Evidence Required for `ABSENT`**: An `ABSENT` status is marked `is_reliable = True` **only** if the portal unambiguously contains an exact absence token (e.g. `ABSENT`, `A`, `UNEXCUSED`). Any accompanying words indicating provisional or unverified attendance (such as `Provisional`, `Pending`, `Medical`, `Duty Leave`, `TBD`) immediately downgrade reliability to `False`.
4. **Stale/Incomplete Pages Fail Closed**: Timeouts, incomplete page renders, or missing attendance tables return diagnostic `UNKNOWN` records with `is_reliable = False`.
5. **Fail-Closed Decision Engine**: The Decision Engine requires `CONFIRMED DAY + RELIABLE PORTAL ABSENCE + VALID PROFESSOR MAPPING + NOT ALREADY NOTIFIED` before flagging a record as `ELIGIBLE_FOR_NOTIFICATION`. Anything else resolves to `NO_ACTION`.

---

## 3. Playwright Browser Automation

Browser automation uses Playwright behind the `PlaywrightBrowserManager` abstraction.

### 3.1 Key Features
- **Isolated Browser Contexts**: Every adapter execution uses an isolated `BrowserContext` with clear separation of cookies, cache, and local storage.
- **Headless by Default**: Fast, resource-efficient background execution (`portal_headless = True`).
- **Interactive / Headed Mode**: Set `PORTAL_HEADLESS=false` when setting up sessions or when manual user interaction (such as MFA or CAPTCHA) is needed.
- **Configurable Timeouts**: Default 30-second navigation/action timeouts (`PORTAL_TIMEOUT_MS=30000`) to prevent hanging processes.
- **Reliable Cleanup**: Contexts and browser instances are cleaned up deterministically via `adapter.close()` or Python context managers (`with adapter:`).

### 3.2 Playwright Setup
Ensure Playwright and browser binaries are installed:

```bash
# Install Python package
pip install playwright>=1.40.0

# Install Chromium browser binary (required for Playwright)
playwright install chromium
```

---

## 4. Local Authentication & Session Handling

To protect user credentials and avoid bypass risks:

1. **Environment Variables**:
   Credentials are read strictly from local environment variables:
   ```bash
   PORTAL_URL="https://portal.yourcollege.edu/attendance"
   PORTAL_USERNAME="student_id"
   PORTAL_PASSWORD="your_password"
   PORTAL_STORAGE_STATE="~/.attendance-automation/storage_state.json"
   ```
2. **Session Persistence**:
   Playwright storage states (cookies and local storage) can be saved locally to avoid repeated logins:
   - Stored in a user-configured file (e.g. `storage_state.json` or `.auth/`).
   - Permissions are explicitly restricted using POSIX `0600` (read/write only by the current user).
   - All session state paths are strictly gitignored (`*storage_state*.json`, `.auth/`, `*.session`).
3. **MFA & Bot Protection**:
   - The application **NEVER** attempts to bypass MFA, 2FA, CAPTCHA, Cloudflare, or other security controls.
   - If MFA or CAPTCHA is detected, the adapter raises an explicit error and prompts the user to authenticate manually in headed mode (`PORTAL_HEADLESS=false`).

---

## 5. Portal Discovery Service

Real college portals vary significantly in design, framework, and selector structure. To avoid inventing selectors:

1. **No Guessing**: The framework never assumes or invents CSS selectors for an unknown portal.
2. **Inspection Tooling**: `PortalDiscoveryService` provides safe, read-only inspection methods:
   - `inspect_login_page()`: Detects login input fields, submit buttons, and CAPTCHA/MFA elements without typing or submitting.
   - `inspect_attendance_page()`: Identifies HTML tables, headers, and row structures on the authenticated page.
   - `detect_mfa_or_captcha()`: Verifies whether bot-mitigation or two-factor gates exist before attempting programmatic login.

---

## 6. How to Add a College-Specific Adapter

Contributors can create adapters tailored to their specific university portal.

### Step 1: Create the Adapter Directory
Create a new directory under `app/adapters/<college_slug>/`:
```text
app/adapters/mycollege/
├── __init__.py
├── adapter.py
├── config.py
└── README.md
```

### Step 2: Implement the Adapter Class
Subclass `BasePortalAdapter`:

```python
from datetime import date
from typing import List, Optional
from app.adapters.base.adapter import BasePortalAdapter, SubjectAttendance
from app.adapters.playwright.browser_manager import PlaywrightBrowserManager
from app.adapters.playwright.normalizer import AttendanceNormalizer
from app.core.enums import AttendanceStatus

class MyCollegePortalAdapter(BasePortalAdapter):
    adapter_name = "mycollege"
    is_read_only = True

    def __init__(self, browser_manager: PlaywrightBrowserManager, config: dict):
        self.browser_manager = browser_manager
        self.config = config

    def validate_config(self) -> bool:
        # Validate that necessary URLs and configuration are provided
        return bool(self.config.get("portal_url"))

    def authenticate(self) -> bool:
        # Check existing session or perform initial login
        # If MFA is required, raise an informative error instructing the user
        return True

    def get_attendance_for_date(self, target_date: date) -> List[SubjectAttendance]:
        # Navigate to attendance page and extract table rows
        # Use AttendanceNormalizer to ensure UNKNOWN never becomes ABSENT
        return []

    def normalize_status(self, raw_status: Optional[str]) -> AttendanceStatus:
        return AttendanceNormalizer.normalize_status(raw_status)

    def close(self) -> None:
        self.browser_manager.close()
```

### Step 3: Register in Factory
Register the adapter in `app/adapters/factory.py`:

```python
from app.adapters.mycollege.adapter import MyCollegePortalAdapter

register_adapter("mycollege", MyCollegePortalAdapter)
```

### Step 4: Write Unit Tests
- Add unit tests under `tests/unit/test_<college_slug>_adapter.py`.
- Mock Playwright components (`Page`, `Locator`, `BrowserContext`) using `unittest.mock`.
- Provide mock HTML fixtures rather than connecting to live university portals during automated test runs.
- Verify fail-closed behavior for all ambiguous or missing portal elements.

---

## 7. Safe Testing & Dry-Run Operation

- **Unit Tests Are Offline**: All unit tests run against mocks. Outbound network sockets are blocked or mocked during unit testing.
- **Dry-Run by Default**: Even when a real portal adapter is configured, notifications are handled by `DryRunNotificationProvider` unless `DRY_RUN=false` is explicitly set in `.env`.
- **Manual Verification**: Run manual dry-run checks via the local dashboard or the API endpoint `POST /api/checks/run` to review parsed attendance and decision results safely without sending real messages.
