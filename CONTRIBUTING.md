# Contributing to Attendance Automation

Thank you for your interest in contributing to **Attendance Automation**! This project is an open-source, local-first platform designed to help students monitor attendance and safely automate correction requests.

Please read this document carefully before submitting pull requests or issues.

---

## Guiding Principles

1. **Local-First & Privacy Preserving**: Student credentials and attendance data must remain strictly on the student's machine. Never introduce telemetry, cloud tracking, or centralized data storage.
2. **Fail-Closed by Design**: If an adapter encounters an unfamiliar portal state, network error, or ambiguous markup, it must return `UNKNOWN` and fail closed. `UNKNOWN` is never treated as `ABSENT`.
3. **No Credential Commits**: Never commit real credentials, student IDs, portal session cookies, or auth tokens. Use fake placeholders and fixtures in all tests.
4. **V1 Read-Only**: The application monitors attendance and generates notifications. It never modifies or attempts to alter records on college portals.

---

## Development Setup

1. **Prerequisites**:
   - Python 3.11+ (Python 3.14 compatible)
   - Virtual environment (`venv`)

2. **Setup Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. **Running Tests**:
   ```bash
   pytest
   ```

4. **Running Application**:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

---

## Adding a New Portal Adapter

We welcome community adapters for different colleges! When building a new adapter:

1. **Directory Structure**:
   Place your adapter under `app/adapters/<college_slug>/`:
   ```text
   app/adapters/<college_slug>/
   ├── __init__.py
   ├── adapter.py
   └── README.md
   ```
2. **Implement the Adapter Contract**:
   Your adapter class must inherit from `BasePortalAdapter` in `app/adapters/base/adapter.py`:
   - `validate_config() -> bool`: Validate that required URLs/credentials are present.
   - `authenticate() -> bool`: Perform authentication (or verify existing session). If interactive MFA/CAPTCHA is required, do not attempt to bypass it—report that manual action is needed.
   - `get_attendance_for_date(target_date: date) -> List[SubjectAttendance]`: Extract attendance records for the target date.
   - `normalize_status(raw_status: str | None) -> AttendanceStatus`: Normalize portal status text to `PRESENT`, `ABSENT`, or `UNKNOWN`.
   - `close() -> None`: Clean up browser contexts, network sessions, or temporary resources.

3. **Register in the Adapter Factory**:
   Register your adapter in `app/adapters/factory.py` using `register_adapter("<college_slug>", YourAdapterClass)`.

4. **Required Adapter Documentation**:
   Every adapter directory must include a `README.md` containing:
   - Supported college portal name and portal software (e.g., Moodle, PeopleSoft, custom portal).
   - Setup instructions and configuration keys.
   - Selector strategy and error-handling assumptions.
   - An explicit confirmation statement: *"No real credentials or private student data are included."*
   - See [docs/PORTAL_ADAPTER_GUIDE.md](docs/PORTAL_ADAPTER_GUIDE.md) for full architectural patterns and safety requirements.

5. **Testing Your Adapter**:
   - Provide unit tests with mock HTML/JSON fixtures in `tests/unit/`.
   - Never run tests against a live production college portal during automated CI.
   - Ensure all parsing logic fails closed to `UNKNOWN` on unexpected or ambiguous markup.

---

## Code Quality & Security Checklist

Before opening a pull request, verify:
- [ ] `pytest` passes with 100% success.
- [ ] No secrets, passwords, cookies, or real URLs are in git diff (`git diff HEAD`).
- [ ] Any new models include proper constraints and indexes.
- [ ] All decision points adhere to the core safety invariant.
- [ ] Logging does not print sensitive student information or auth headers.
