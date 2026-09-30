#!/usr/bin/env python3
"""Manual verification script for the Gmail Notification Provider.

SECURITY & AUDIT NOTE:
- Automated tests MUST NEVER call this script with real credentials.
- Real email transmission requires explicit interactive operator confirmation.
- Secrets are NEVER logged or displayed to the terminal.
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Auto-reexec with local venv if available
venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
if venv_python.exists() and sys.executable != str(venv_python) and not os.environ.get("ATTENDANCE_VENV_REEXEC"):
    os.environ["ATTENDANCE_VENV_REEXEC"] = "1"
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

from app.config import get_settings
from app.notifications.base import NotificationPayload
from app.notifications.gmail import GmailClient, GmailConfig, GmailNotificationProvider
from app.notifications.oauth import FileTokenStorage, GoogleOAuthClient
from app.security.redaction import redact_string

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gmail.verify")


def print_status(settings, token_storage, oauth_client) -> bool:
    """Print safe provider status without exposing credentials."""
    configured = bool(settings.gmail_client_id and settings.gmail_client_secret)
    token = token_storage.load_token()
    token_exists = token is not None
    is_expired = token.is_expired() if token else False
    has_refresh = token.has_refresh_token() if token else False
    connected = token_exists and (not is_expired or has_refresh)

    print("\n" + "=" * 60)
    print(" GMAIL NOTIFICATION PROVIDER - STATUS REPORT")
    print("=" * 60)
    print(f" Client ID Configured   : {'YES' if settings.gmail_client_id else 'NO'}")
    print(f" Client Secret Set       : {'YES' if settings.gmail_client_secret else 'NO'}")
    print(f" Redirect URI            : {settings.gmail_redirect_uri}")
    print(f" Token Storage File      : {token_storage.file_path}")
    print(f" Stored Token Exists     : {'YES' if token_exists else 'NO'}")
    if token:
        print(f" Token Expired           : {'YES' if is_expired else 'NO'}")
        print(f" Has Refresh Token       : {'YES' if has_refresh else 'NO'}")
    print(f" Connection Status       : {'CONNECTED' if connected else ('CONFIGURED (NOT AUTHORIZED)' if configured else 'NOT CONFIGURED')}")
    print(f" Sender Email            : {settings.notification_sender_email}")
    print(f" App Safe Mode (Dry Run) : {settings.dry_run}")
    print("=" * 60 + "\n")
    return connected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual verification tool for Gmail notification adapter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check configuration and authorization status without sending email.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate message generation and dispatch without contacting Gmail API.",
    )
    parser.add_argument(
        "--send-test-email",
        metavar="RECIPIENT_EMAIL",
        help="Send a real verification email. REQUIRES interactive operator confirmation.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass interactive confirmation prompt (use ONLY in controlled manual environments).",
    )

    args = parser.parse_args()
    settings = get_settings()

    token_file = settings.gmail_token_file or "credentials/gmail_token.json"
    token_storage = FileTokenStorage(token_file)

    gmail_config = GmailConfig(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        redirect_uri=settings.gmail_redirect_uri,
        token_file=token_file,
        sender_email=settings.notification_sender_email,
    )
    oauth_client = GoogleOAuthClient(config=gmail_config, token_storage=token_storage)

    if args.status or (not args.dry_run and not args.send_test_email):
        is_connected = print_status(settings, token_storage, oauth_client)
        if not is_connected:
            print("To authorize Gmail, run the web application and navigate to Settings to connect.")
        return 0

    if args.dry_run:
        print("\n--- Running Dry-Run Simulation ---")
        client = GmailClient(config=gmail_config, oauth_client=oauth_client)
        provider = GmailNotificationProvider(client=client, is_dry_run=True)

        payload = NotificationPayload(
            subject_code="TEST101",
            subject_name="Software Verification Testing",
            target_date=date.today(),
            recipient_email="test-recipient@example.edu",
            professor_name="Test Instructor",
            message_subject="[VERIFICATION] Attendance Discrepancy Notice",
            message_body="This is a test notification generated by scripts/verify_gmail_provider.py in dry-run mode.",
        )

        outcome = provider.send(payload)
        print(f"Dry-run Outcome : success={outcome.success}, is_dry_run={outcome.is_dry_run}")
        print(f"Message Preview :\n{outcome.message_preview}")
        print("Dry-run verification completed successfully. No real email was transmitted.\n")
        return 0

    if args.send_test_email:
        recipient = args.send_test_email.strip()
        if "@" not in recipient:
            print(f"Error: Invalid recipient email '{recipient}'.", file=sys.stderr)
            return 1

        is_connected = print_status(settings, token_storage, oauth_client)
        if not is_connected:
            print("Error: Gmail provider is not authorized. Please complete OAuth authorization first.", file=sys.stderr)
            return 1

        print("\n" + "!" * 60)
        print(" CAUTION: REAL EMAIL TRANSMISSION REQUESTED")
        print("!" * 60)
        print(f" Recipient : {recipient}")
        print(f" Sender    : {settings.notification_sender_email or 'Authorized Gmail User'}")
        print("!" * 60)

        if not args.force:
            confirmation = input("Type 'CONFIRM' to send real test email: ").strip()
            if confirmation != "CONFIRM":
                print("Aborted. No email sent.")
                return 0

        client = GmailClient(config=gmail_config, oauth_client=oauth_client)
        provider = GmailNotificationProvider(client=client, is_dry_run=False)

        payload = NotificationPayload(
            subject_code="TEST101",
            subject_name="Attendance Automation Platform Verification",
            target_date=date.today(),
            recipient_email=recipient,
            professor_name="Verification Reviewer",
            message_subject="[Attendance Platform] Manual Provider Verification Email",
            message_body=(
                f"Dear Reviewer,\n\n"
                f"This email confirms that the Gmail Notification Provider for Attendance Automation "
                f"has been successfully authorized and verified on {date.today().isoformat()}.\n\n"
                f"Regards,\nAttendance Automation Platform"
            ),
        )

        try:
            print("Sending real email via Gmail API...")
            outcome = provider.send(payload)
            print(f"Send Success! Message ID: {outcome.details.get('external_id')}")
            return 0
        except Exception as exc:
            safe_err = redact_string(str(exc))
            print(f"Send Failed: {safe_err}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
