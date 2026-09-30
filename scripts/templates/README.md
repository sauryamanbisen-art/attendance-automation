# OS Scheduler Setup Guide

This directory contains configuration templates for running the automated daily attendance check at the OS level (macOS `launchd`, Linux `cron`, and Linux `systemd`).

## Prerequisites

1. Ensure the repository virtualenv has dependencies installed:
   ```bash
   poetry install  # or python -m venv .venv && pip install -r requirements.txt
   ```
2. Create the `logs/` directory in your project root:
   ```bash
   mkdir -p logs
   ```
3. Ensure `.env` is configured with desired settings:
   ```ini
   TIMEZONE="Asia/Kolkata"
   CUTOFF_TIME="16:00"
   DRY_RUN=true
   PORTAL_ADAPTER="pwioi"
   ```

---

## 1. macOS (`launchd`)

macOS uses `launchd` via User LaunchAgents to run scheduled jobs inside the user session.

### Installation

1. Copy the plist template to `~/Library/LaunchAgents/`:
   ```bash
   cp scripts/templates/com.attendance.dailycheck.plist ~/Library/LaunchAgents/
   ```
2. Edit `~/Library/LaunchAgents/com.attendance.dailycheck.plist` and replace `/REPLACE_WITH_PROJECT_ROOT` with your absolute repository path (e.g., `/Users/yourusername/attendance-automation`).
3. Load the LaunchAgent:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.attendance.dailycheck.plist
   ```
4. Verify it is loaded:
   ```bash
   launchctl list | grep com.attendance.dailycheck
   ```
5. To unload/disable:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.attendance.dailycheck.plist
   ```

---

## 2. Linux Cron (`crontab`)

1. Open your user crontab editor:
   ```bash
   crontab -e
   ```
2. Add the line from `crontab.example`, replacing `/REPLACE_WITH_PROJECT_ROOT` with your actual directory:
   ```cron
   5 16 * * * cd /path/to/attendance-automation && /path/to/attendance-automation/.venv/bin/python /path/to/attendance-automation/scripts/run_daily_check.py >> /path/to/attendance-automation/logs/daily_check.log 2>&1
   ```

---

## 3. Linux Systemd (User Timer)

1. Copy unit files to `~/.config/systemd/user/`:
   ```bash
   mkdir -p ~/.config/systemd/user
   cp scripts/templates/systemd/attendance-check.service ~/.config/systemd/user/
   cp scripts/templates/systemd/attendance-check.timer ~/.config/systemd/user/
   ```
2. Replace `/REPLACE_WITH_PROJECT_ROOT` in `attendance-check.service` with your actual repository path.
3. Reload systemd daemon and enable timer:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now attendance-check.timer
   ```
4. Check timer status:
   ```bash
   systemctl --user list-timers --all
   ```

---

## Testing Manually

You can test the check at any time from your terminal:

```bash
# Bypass cutoff check for testing:
.venv/bin/python scripts/run_daily_check.py --ignore-cutoff

# Dry-run with explicit fake adapter:
.venv/bin/python scripts/run_daily_check.py --ignore-cutoff --adapter fake

# Verbose output:
.venv/bin/python scripts/run_daily_check.py --ignore-cutoff -v
```
