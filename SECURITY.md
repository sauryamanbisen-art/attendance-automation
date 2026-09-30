# Security Policy

## Security Overview & Core Principles

**Attendance Automation** is an open-source, local-first platform designed with security and privacy as first-class architectural requirements.

- **Local-First / No Central Server**: Student credentials, session cookies, tokens, and personal attendance records remain strictly local to the user's machine.
- **Fail-Closed Design**: Any uncertain portal status, missing confirmation, parse error, or missing mapping defaults safely to `NO_ACTION`.
- **Read-Only Portal Policy**: In V1, the application never attempts to write, alter, or manipulate college portal attendance records.
- **Least-Privilege Authorization**: Email (Gmail API `gmail.send` scope only) and Google Chat integrations use minimal required OAuth 2.0 scopes. The application never stores or requests raw user passwords.
- **Restricted Token Storage**: OAuth tokens are saved with POSIX 0600 file permissions in gitignored credential directories, ensuring tokens are only readable by the local user process.

---

## Secret Handling & Rules for Contributors and Users

1. **Never Commit Secrets**: Never commit `.env` files, API keys, client secrets, passwords, cookies, tokens, or browser session files (`storage_state/`, `playwright/.auth/`).
2. **Never Log Sensitive Data**: Secrets, authorization headers, passwords, and sensitive student identifiers must never appear in application logs or stack traces.
3. **Safe Test Fixtures**: All unit, integration, and adapter tests must use fake or mock credentials. Real credentials must never be added to test files.
4. **Credential Storage**: For production usage, sensitive credentials should preferably be stored in OS credential storage (such as macOS Keychain) or runtime environment variables rather than plain text.
5. **No Secrets in Issues/PRs**: When submitting bug reports or pull requests, ensure that URLs, tokens, session IDs, screenshots, and logs are completely sanitized and redacted.

---

## Threat Model & Mitigations

| Threat | Risk Level | Mitigation Strategy |
| :--- | :--- | :--- |
| **Accidental Secret Commit** | High | `.gitignore` covers `.env`, DBs, cookies, session states; automated pre-commit and CI secret scanning. |
| **Log Leakage** | Medium | Automated log redaction filter masks sensitive keys (`password`, `token`, `secret`, `cookie`). |
| **Stolen Browser Sessions** | High | Session storage and browser state directories are kept strictly local and gitignored. |
| **Duplicate Notifications** | High | Unique constraints on `(date, subject_id)` enforce database-level deduplication. |
| **Portal UI / Parsing Drift** | Medium | Fail-closed parsing returns `UNKNOWN`, preventing unintended notifications. |
| **Unintended Portal Write** | High | Read-only adapter architecture with zero write endpoints in V1. |
| **Unintended Email Dispatch** | High | `DRY_RUN=true` mode by default; explicit confirmation required before sending. |

---

## Reporting a Vulnerability

If you discover a security vulnerability or secret leakage in this repository, please do **NOT** open a public GitHub issue.

Instead, please report it privately:
- **Email**: `security@attendance-automation.local` (or contact repository maintainers directly)
- **GitHub**: Use GitHub Private Vulnerability Reporting on the repository.

Please include:
- A description of the issue and potential impact
- Steps or a minimal proof of concept to reproduce the issue
- Affected components or adapters

Reports will be acknowledged promptly and addressed before public disclosure.
