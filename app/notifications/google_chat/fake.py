"""Fake Google Chat client for testing, demonstration, and offline execution."""

from typing import Any, Optional


class FakeGoogleChatClient:
    """Mock client for Google Chat API that records messages in-memory.

    Guarantees:
    - Never makes network or HTTP requests.
    - Records sent message payloads in `sent_messages` list.
    - Configurable to simulate failures (exceptions) for testing error handling.
    """

    def __init__(
        self,
        should_fail: bool = False,
        fail_exception: Optional[Exception] = None,
        dm_spaces: Optional[dict[str, str]] = None,
    ) -> None:
        self.should_fail = should_fail
        self.fail_exception = fail_exception
        self.sent_messages: list[dict[str, Any]] = []
        self.dm_spaces: dict[str, str] = dict(dm_spaces or {})

    def find_direct_message(self, user_email: str) -> dict[str, Any]:
        """Simulate direct message discovery."""
        if self.should_fail:
            if self.fail_exception is not None:
                raise self.fail_exception
            from app.notifications.google_chat.exceptions import GoogleChatApiError
            raise GoogleChatApiError("Simulated Google Chat findDirectMessage failure")

        cleaned = user_email.strip().lower()
        if not cleaned or "@" not in cleaned:
            from app.notifications.google_chat.exceptions import GoogleChatRecipientError
            raise GoogleChatRecipientError(f"Invalid professor email address: '{user_email}'.")

        space = self.dm_spaces.get(cleaned) or self.dm_spaces.get(f"users/{cleaned}")
        if not space:
            from app.notifications.google_chat.exceptions import GoogleChatRecipientError
            raise GoogleChatRecipientError(
                f"No direct message space exists with '{user_email}'. "
                f"A direct message conversation must be initiated first in Google Chat."
            )

        from app.notifications.google_chat.client import GoogleChatClient
        formatted_space = GoogleChatClient.normalize_space_name(space)
        return {
            "name": formatted_space,
            "spaceType": "DIRECT_MESSAGE",
            "type": "DIRECT_MESSAGE",
        }

    def send_message(
        self,
        space_name: str,
        text: str,
        cards: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Record the message send attempt or simulate failure."""
        if self.should_fail:
            if self.fail_exception is not None:
                raise self.fail_exception
            from app.notifications.google_chat.exceptions import GoogleChatApiError
            raise GoogleChatApiError("Simulated Google Chat API delivery failure")

        msg_id = f"fake_msg_{len(self.sent_messages) + 1}"
        record = {
            "name": f"{space_name}/messages/{msg_id}",
            "space_name": space_name,
            "text": text,
            "cards": cards,
        }
        self.sent_messages.append(record)
        return {"name": record["name"], "text": text}
