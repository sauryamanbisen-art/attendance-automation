"""OAuth 2.0 authentication client and token management for Google Chat.

This module re-exports shared Google OAuth classes from app.notifications.oauth
for backwards compatibility with existing Google Chat modules.
"""

from app.notifications.oauth import (
    BaseTokenStorage,
    FileTokenStorage,
    GoogleOAuthClient,
    InMemoryTokenStorage,
    OAuthConfigProtocol,
    OAuthToken,
)

# Maintain backwards compatibility
GoogleChatOAuthClient = GoogleOAuthClient

__all__ = [
    "OAuthToken",
    "BaseTokenStorage",
    "InMemoryTokenStorage",
    "FileTokenStorage",
    "OAuthConfigProtocol",
    "GoogleOAuthClient",
    "GoogleChatOAuthClient",
]
