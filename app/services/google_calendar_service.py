"""Service for fetching the real schedule from Google Calendar."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
import re

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.subject import Subject, VALID_CURRICULUM_CODES
from app.services.gmail_oauth_service import GmailOAuthService

logger = logging.getLogger(__name__)

class GoogleCalendarServiceError(Exception):
    pass


@dataclass
class ScheduledClass:
    """Represents a scheduled class extracted from a Google Calendar event."""
    subject: Subject
    start_time: time
    end_time: time
    is_extra: bool = False
    is_cancelled: bool = False


class GoogleCalendarService:
    """Fetches real schedule from Google Calendar."""

    def __init__(self, db: Session, oauth_service: Optional[GmailOAuthService] = None):
        self.db = db
        self.oauth_service = oauth_service or GmailOAuthService()
        self.settings = get_settings()

    def get_events_for_date(self, target_date: date) -> List[dict]:
        """Fetch all calendar events for the given date from the primary calendar."""
        token = self.oauth_service.token_storage.load_token()
        if not token:
            raise GoogleCalendarServiceError("GOOGLE_AUTH_REQUIRED")
            
        if token.is_expired():
            # Attempt to refresh
            if token.has_refresh_token():
                logger.info("Token expired. Refreshing...")
                try:
                    token = self.oauth_service.oauth_client.refresh_access_token()
                except Exception as e:
                    logger.error(f"Failed to refresh OAuth token: {e}")
                    raise GoogleCalendarServiceError("GOOGLE_AUTH_REQUIRED")
            else:
                raise GoogleCalendarServiceError("GOOGLE_AUTH_REQUIRED")

        tz_str = self.settings.timezone or "Asia/Kolkata"
        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            tz = timezone.utc

        # Start of day
        time_min = datetime.combine(target_date, time.min, tzinfo=tz).isoformat()
        # End of day
        time_max = datetime.combine(target_date, time.max, tzinfo=tz).isoformat()

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        headers = {
            "Authorization": f"Bearer {token.access_token}"
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params, headers=headers)
            
            if resp.status_code != 200:
                error_msg = f"Failed to fetch calendar events: HTTP {resp.status_code} - {resp.text}"
                logger.error(error_msg)
                raise GoogleCalendarServiceError(error_msg)
                
            data = resp.json()
            return data.get("items", [])

    def get_scheduled_classes(self, target_date: date) -> List[ScheduledClass]:
        """Extract valid subjects from the events for the target date."""
        events = self.get_events_for_date(target_date)
        scheduled_classes = []
        
        # We need all subjects to map against.
        all_subjects = self.db.query(Subject).all()
        code_to_subject = {s.code: s for s in all_subjects}
        name_to_subject = {s.name.lower(): s for s in all_subjects}
        
        for event in events:
            title = event.get("summary", "")
            if not title:
                continue
                
            # Find subject code in title (e.g. 306JWD)
            found_subject = None
            for code in VALID_CURRICULUM_CODES:
                if code in title.upper():
                    found_subject = code_to_subject.get(code)
                    break
            
            if not found_subject:
                # Try by exact name match if code not present
                for name, subj in name_to_subject.items():
                    if name in title.lower():
                        found_subject = subj
                        break
            
            if found_subject:
                # Extract start and end times
                start = event.get("start", {})
                end = event.get("end", {})
                
                # Format: "2026-10-06T09:00:00+05:30"
                start_dt_str = start.get("dateTime")
                end_dt_str = end.get("dateTime")
                
                if start_dt_str and end_dt_str:
                    try:
                        start_time = datetime.fromisoformat(start_dt_str).time()
                        end_time = datetime.fromisoformat(end_dt_str).time()
                        
                        is_cancelled = "cancelled" in title.lower() or event.get("status") == "cancelled"
                        
                        scheduled_classes.append(
                            ScheduledClass(
                                subject=found_subject,
                                start_time=start_time,
                                end_time=end_time,
                                is_cancelled=is_cancelled,
                            )
                        )
                    except ValueError:
                        continue

        return scheduled_classes
