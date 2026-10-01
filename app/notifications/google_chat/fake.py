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
    ) -> None:
        self.should_fail = should_fail
        self.fail_exception = fail_exception
        self.sent_messages: list[dict[str, Any]] = []

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
