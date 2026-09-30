# Attendance Automation Platform

> **Open-Source • Local-First • Multi-College • Security-First • Fail-Closed**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)

Attendance Automation is an open-source, local-first platform designed to help college students monitor attendance records on their university portal. When a student explicitly confirms their attendance for a specific day, the system checks the portal after a configured cutoff time, detects discrepancies where the student was marked absent by mistake, and prepares/sends a polite correction request to the assigned professor.

---

## 🛡️ Core Safety Invariant

```text
CONFIRMED DAY + RELIABLE PORTAL ABSENCE + VALID PROFESSOR MAPPING + NOT ALREADY NOTIFIED
= ELIGIBLE CORRECTION NOTIFICATION
```

**Every other path is strictly fail-closed (`NO_ACTION`).**

- **No Attendance Confirmation?** → `NO_ACTION`
- **Attendance Marked Present?** → `NO_ACTION`
- **Attendance Marked Unknown / Ambiguous / Error?** → `NO_ACTION`
- **Missing Professor Mapping?** → `NO_ACTION`
- **Already Notified Today for Subject?** → `NO_ACTION`
- **Dry-Run Mode Enabled?** → Generates decision without dispatching real email.

---

## 🏛️ Architecture Overview

```text
+-------------------------------------------------------------------------+
|                              Local Student Machine                       |
|                                                                         |
|  +--------------------+      +--------------------+      +-----------+  |
|  | Local Web/API UI   | ---> | Confirmation Svc   | ---> | SQLite DB |  |
|  | (FastAPI Dashboard)|      | ("I Went To Coll") |      | (Local)   |  |
|  +--------------------+      +--------------------+      +-----------+  |
|            |                           |                       ^        |
|            v                           v                       |        |
|  +--------------------+      +--------------------+            |        |
|  | Portal Adapter     | ---> |  Decision Engine   | -----------+        |
|  | (Fake / College)   |      |   (Fail-Closed)    |            |        |
|  +--------------------+      +--------------------+            |        |
|                                        |                       v        |
|                                        v                 +-----------+  |
|                              +--------------------+      | Audit Log |  |
|                              | Notification Engine| ---> | (Run IDs) |  |
|                              | (Gmail/Chat/Dry-Run)|    +-----------+  |
|                              +--------------------+                     |
+-------------------------------------------------------------------------+
```

### Key Architectural Pillars

1. **Local-First & Zero Central Telemetry**:
   Your credentials, session cookies, and attendance history stay on your machine. There is no central backend database or telemetry service.
2. **Adapter Plugin Architecture**:
   The core decision logic is decoupled from college portal quirks. Anyone can contribute a custom portal adapter by implementing `BasePortalAdapter`.
3. **Fail-Closed Principle**:
   `UNKNOWN` is **never** treated as `ABSENT`. Ambiguous portal states, timeouts, or changes in portal HTML never trigger accidental emails.
4. **Read-Only Portal Access**:
   V1 is strictly read-only. It never modifies college portal attendance records or circumvents authentication controls.
5. **Idempotent Operations**:
   Daily confirmation is idempotent and scoped strictly to the selected date. Notifications are deduplicated at the database constraint level `(date, subject_id)`.

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11+
- Virtual environment (`.venv`)

### 2. Setup
```bash
# Clone the repository
git clone https://github.com/your-username/attendance-automation.git
cd attendance-automation

# Activate your virtual environment
source .venv/bin/activate

# Install dependencies (in editable mode with dev tools)
pip install -e ".[dev]"

# Create your local environment configuration
cp .env.example .env
```

### 3. Run the Development Server
```bash
uvicorn main:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser to access the local API and documentation.
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### 4. Playwright Setup (Optional for Live Portal Adapters)
If running a live Playwright portal adapter (rather than the default deterministic `FakePortalAdapter`):
```bash
playwright install chromium
```

### 5. Run the Test Suite
```bash
pytest
```

---

## 🔌 Portal Adapter Framework

The system uses a pluggable, strictly **read-only** portal adapter architecture:
- **`FakePortalAdapter`**: Default deterministic adapter providing instant mock data for development and testing without network access.
- **`GenericPlaywrightPortalAdapter`**: Headless browser automation powered by Playwright with isolated browser contexts, safe credential injection, and strict fail-closed attendance parsing.
- **`PWIOIPortalAdapter`**: Dedicated adapter for the PWIOI student portal with Google sign-in session handling and attendance aggregation.
- **`AttendanceNormalizer`**: Guaranteed mapping to domain statuses (`PRESENT`, `ABSENT`, `UNKNOWN`). `UNKNOWN` is never treated as `ABSENT`. Missing rows or unexpected labels fail closed with `is_reliable = False`.
- **`PortalDiscoveryService`**: Read-only portal inspection utility to analyze login forms and table markup without guessing selectors or modifying records.

For portal adapter developer instructions, see [docs/PORTAL_ADAPTER_GUIDE.md](docs/PORTAL_ADAPTER_GUIDE.md).
For Gmail OAuth setup and verification instructions, see [docs/GMAIL_OAUTH_SETUP_AND_TEST_GUIDE.md](docs/GMAIL_OAUTH_SETUP_AND_TEST_GUIDE.md).

---

## 📁 Repository Layout

```text
attendance-automation/
├── app/
│   ├── adapters/          # Pluggable portal adapter implementations
│   │   ├── base/          # BasePortalAdapter abstract interface & exceptions
│   │   ├── fake/          # FakePortalAdapter for testing without a live portal
│   │   ├── playwright/    # Playwright browser manager, normalizer, and adapter
│   │   ├── pwioi/         # PWIOI student portal adapter & aggregation logic
│   │   └── factory.py     # Adapter registry and factory
│   ├── api/               # FastAPI route controllers
│   ├── config/            # Pydantic Settings and environment configuration
│   ├── core/              # Domain enums, logging with redaction, constants
│   ├── database/          # SQLAlchemy session, engine, and base configuration
│   ├── models/            # SQLAlchemy database models
│   ├── notifications/     # Notification providers (Dry-run, Gmail OAuth, Google Chat OAuth)
│   ├── security/          # Secret management & redaction helpers
│   └── services/          # Confirmation service, Decision engine, Audit service
├── docs/                  # Architectural documentation & setup guides
├── frontend/              # Local web dashboard UI assets
├── scripts/               # Helper scripts (DB migrations, scheduling)
├── tests/
│   ├── fixtures/          # Test datasets and mock responses
│   ├── integration/       # API & end-to-end integration tests
│   └── unit/              # Isolated unit tests (Decision Engine, Models, Adapters)
├── .env.example           # Safe environment variables template
├── .gitignore             # Safety ignores (.env, DBs, sessions, tokens)
├── pyproject.toml         # Packaging and dependency configuration
├── README.md              # Project documentation
├── SECURITY.md            # Security policy and vulnerability disclosure
├── CONTRIBUTING.md        # Adapter and contribution guidelines
└── LICENSE                # MIT License
```

---

## 🔒 Security & Privacy

For full security policies and threat models, see [SECURITY.md](SECURITY.md).

- **No Secrets in Git**: Local `.env`, SQLite databases (`*.db`), browser states (`playwright/.auth/`), and logs are strictly ignored by Git.
- **Log Masking**: Passwords, tokens, cookies, and secret values are automatically sanitized in log outputs.
- **Least-Privilege Email**: Gmail integration requires OAuth token authorization with send-only scope; student email passwords are never stored.

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
