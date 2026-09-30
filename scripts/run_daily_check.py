#!/usr/bin/env python3
"""Daily Attendance Automation CLI Runner.

Intended for execution by OS schedulers (macOS launchd, Linux cron / systemd)
or manual operator invocation.

Features:
- Enforces cutoff time (default 16:00 / 4 PM)
- Enforces student attendance confirmation ('I WENT TO COLLEGE')
- Dry-run enabled by default
- Fail-closed error handling
- Audit logging for all lifecycle events
- Safe duplicate runs (deduplication)
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path when invoked directly by OS schedulers or shell
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# If running outside the local virtualenv, auto-reexec with .venv/bin/python if available
venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
if venv_python.exists() and sys.executable != str(venv_python) and not os.environ.get("ATTENDANCE_VENV_REEXEC"):
    os.environ["ATTENDANCE_VENV_REEXEC"] = "1"
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

from app.config import get_settings
from app.database.session import SessionLocal, init_db
from app.services.daily_scheduler import DailyCheckResult, DailyCheckRunner

logger = logging.getLogger("attendance.scheduler")


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging for CLI and scheduler runs."""
    level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=log_format, stream=sys.stdout)


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI options for the scheduled check runner."""
    parser = argparse.ArgumentParser(
        description="Run scheduled daily attendance verification and discrepancy processing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--date",
        type=lambda d: datetime.strptime(d, "%Y-%m-%d").date(),
        default=None,
        help="Target date to evaluate (YYYY-MM-DD). Defaults to current date in configured timezone.",
    )
    parser.add_argument(
        "--ignore-cutoff",
        action="store_true",
        default=False,
        help="Bypass cutoff time check (for manual testing or historical verification).",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_const",
        const=True,
        default=None,
        help="Enforce dry-run mode (no external notifications sent).",
    )
    mode_group.add_argument(
        "--live",
        dest="dry_run",
        action="store_const",
        const=False,
        help="Run in live mode (dispatch real notifications if eligible).",
    )

    parser.add_argument(
        "--adapter",
        type=str,
        default=None,
        choices=["pwioi", "fake", "generic", "generic_playwright"],
        help="Override portal adapter implementation (defaults to PORTAL_ADAPTER from settings).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed debug logs.",
    )
    return parser.parse_args(args)


def format_summary(result: DailyCheckResult) -> str:
    """Format execution summary for CLI output."""
    lines = [
        "=" * 50,
        " ATTENDANCE CHECK SUMMARY",
        "=" * 50,
        f"Run ID:            {result.run_id}",
        f"Target Date:       {result.target_date.isoformat()}",
        f"Status:            {result.status}",
        f"Dry Run:           {result.dry_run}",
    ]
    if result.reason:
        lines.append(f"Reason:            {result.reason}")
    if result.error_message:
        lines.append(f"Error:             {result.error_message}")
    if result.status == "SUCCESS":
        lines.extend([
            f"Subjects Checked:  {result.subjects_checked}",
            f"Eligible Records:  {result.eligible_count}",
            f"Notifications:     {result.notifications_sent}",
        ])
        if result.decisions:
            lines.append("-" * 50)
            lines.append("Decisions:")
            for d in result.decisions:
                lines.append(
                    f"  - [{d.subject_code}] {d.action.value} ({d.reason.value}) "
                    f"status={d.status.value} reliable={d.is_reliable}"
                )
    lines.append("=" * 50)
    return "\n".join(lines)


def main(args: Optional[list[str]] = None) -> int:
    """CLI entrypoint returning exit code."""
    parsed = parse_args(args)
    setup_logging(verbose=parsed.verbose)

    settings = get_settings()
    init_db()

    db = SessionLocal()
    try:
        runner = DailyCheckRunner(db=db, settings=settings)
        result = runner.run_daily_check(
            target_date=parsed.date,
            ignore_cutoff=parsed.ignore_cutoff,
            adapter_name=parsed.adapter,
            dry_run=parsed.dry_run,
        )

        summary_text = format_summary(result)
        print(summary_text)

        if result.status == "FAILED":
            logger.error("Daily attendance check failed: %s", result.error_message)
            return 1

        logger.info("Daily attendance check completed with status: %s", result.status)
        return 0
    except Exception as exc:
        logger.exception("Unexpected error during daily attendance check: %s", exc)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
