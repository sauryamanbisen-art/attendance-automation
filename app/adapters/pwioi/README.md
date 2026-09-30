# PWIOI Student Portal Adapter (`pwioi`)

This adapter integrates Attendance Automation with the **PWIOI Student Portal** (`https://app.pwioi.club`).

---

## 1. Overview & Architecture

- **Portal Name**: PWIOI Student Portal (Next.js Application)
- **Portal Base URL**: `https://app.pwioi.club`
- **Login URL**: `https://app.pwioi.club/auth/student/login`
- **Attendance URL**: `https://app.pwioi.club/dashboard/student/attendance`
- **Adapter Slug**: `pwioi`
- **Operation Mode**: Strictly **READ-ONLY**

---

## 2. Authentication Flow

PWIOI authentication uses **Google Sign-In**:

- **No Credential Automation**: The adapter **never** attempts to automate Google account passwords, bypass 2FA/MFA, or circumvent Google security challenges.
- **Initial Setup (Interactive)**: Run in headed mode (`PORTAL_HEADLESS=false`) to open Chromium and allow the student to complete Google Sign-In manually.
- **Session Persistence**: Upon successful sign-in, Playwright storage state is saved to `storage_state/pwioi_session.json` with POSIX `0600` permissions (`-rw-------`).
- **Subsequent Runs**: Future checks load the local storage state directly and verify that the session is still active on `/dashboard/student/attendance`.
- **Git Security**: Session states, auth files, cookies, and tokens are strictly excluded by `.gitignore`.

---

## 3. Configuration

Configure via `.env` or environment variables:

```bash
# Set portal adapter to pwioi
PORTAL_ADAPTER=pwioi

# PWIOI specific endpoints (defaults shown)
PWIOI_PORTAL_URL=https://app.pwioi.club/auth/student/login
PWIOI_ATTENDANCE_URL=https://app.pwioi.club/dashboard/student/attendance
PWIOI_STORAGE_STATE=storage_state/pwioi_session.json

# Optional: Academic Term (e.g. "3"). If unset, active term is detected.
PWIOI_ACADEMIC_TERM=3

# Headless mode (set to false for first-time manual Google Sign-In)
PORTAL_HEADLESS=true
PORTAL_TIMEOUT_MS=15000

# Optional browser channel: set to "chrome" to use system-installed Google Chrome
PWIOI_BROWSER_CHANNEL=chrome
```

---

## 4. Attendance Parsing & Aggregation

### Course Discovery
The adapter locates the "Course Breakdown" section on the dashboard and extracts course codes and names using standard patterns:
- `306JWD` — OJT / Java Web Developer (Spring Boot)
- `304ELS` — Essential Language Skills
- `302OPS` — Operating System
- `304VEP` — Data Visualization using Excel and Powerbi
- `301ADS` — Advance Data Structures and Algorithms
- `303PDS` — Python for Data Science

### Daily Records & Multiple Periods
For each course, the adapter accesses "Daily Records" and locates records matching the target date.
Because a course may have multiple periods on a single date (e.g. `2026-08-04-period 1`, `2026-08-04-period 2`), the adapter aggregates them safely:

1. **No records on date**: `UNKNOWN` (unreliable, no class scheduled).
2. **Any period ambiguous / UNKNOWN / provisional**: `UNKNOWN` (fail-closed, `is_reliable=False`).
3. **All periods PRESENT**: `PRESENT` (`is_reliable=True`).
4. **Any period reliably ABSENT**: `ABSENT` (`is_reliable=True`), recording absent periods in metadata.
5. All period breakdowns are preserved in `metadata["periods"]`.

### Delayed Attendance Updates & Auto-Refresh
After cutoff time (e.g. 4 PM), PWIOI may initially display `NOT MARKED` or omit the day's record while professors finalize logs:
- **Automatic Reload**: The adapter detects `NOT MARKED`, `UNMARKED`, missing rows, or provisional indicators and automatically reloads the page via Playwright.
- **Configurable Retries**: Configured via `max_retries` (default `3`) and `retry_delay_seconds` (default `2.0s`).
- **Safety Invariant**: If attendance becomes `PRESENT` or reliable `ABSENT`, it is parsed and dispatched. If it remains `NOT MARKED` after all retries, it fails closed to `UNKNOWN` with `is_reliable=False`. `NOT MARKED` is **never** converted into `ABSENT`.
- **Audit Logging**: Retry attempts and refresh status are preserved in `SubjectAttendance.metadata["retries_attempted"]` and `metadata["refreshed"]`.

---

## 5. Security & Safety Statement

- **Strictly Read-Only**: This adapter only reads attendance pages. It contains zero methods to modify, post, or update attendance records on PWIOI.
- **No Secret Commits**: *No real credentials, passwords, student IDs, session cookies, or private student data are included or committed in this repository.*
- **Offline Testing**: All automated tests run against mocked page objects or synthetic HTML fixtures.
