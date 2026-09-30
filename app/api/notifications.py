"""Notification setup and authorization endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.gmail import get_gmail_oauth_service
from app.api.google_chat import get_google_chat_service
from app.api.schemas import NotificationProvidersResponse, ProviderStatus
from app.config import Settings, get_settings
from app.database import get_db
from app.services.gmail_oauth_service import GmailOAuthService
from app.services.google_chat_oauth_service import GoogleChatOAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/providers", response_model=NotificationProvidersResponse)
def list_providers(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    gc_service: GoogleChatOAuthService = Depends(get_google_chat_service),
    gmail_service: GmailOAuthService = Depends(get_gmail_oauth_service),
) -> NotificationProvidersResponse:
    """Retrieve the connection status of all supported notification providers."""
    providers = []

    # Google Chat Provider
    gc_status = gc_service.get_connection_status(db=db)
    gc_account = gc_status.get("default_space") if gc_status.get("connected") else None
    providers.append(
        ProviderStatus(
            id="google_chat",
            name="Google Chat",
            connected=gc_status["connected"],
            is_configured=gc_status["configured"],
            auth_url="/api/auth/google-chat/authorize?redirect=true",
            account_identifier=gc_account,
        )
    )

    # Gmail Provider
    gmail_status = gmail_service.get_connection_status(db=db)
    gmail_account = settings.notification_sender_email if gmail_status.get("connected") else None
    providers.append(
        ProviderStatus(
            id="gmail",
            name="Gmail",
            connected=gmail_status["connected"],
            is_configured=gmail_status["configured"],
            auth_url="/api/auth/gmail/authorize?redirect=true",
            account_identifier=gmail_account,
        )
    )

    return NotificationProvidersResponse(providers=providers)


@router.delete("/{provider_id}/authorization", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_provider(
    provider_id: str,
    gc_service: GoogleChatOAuthService = Depends(get_google_chat_service),
    gmail_service: GmailOAuthService = Depends(get_gmail_oauth_service),
) -> None:
    """Securely disconnect a notification provider by deleting its local authorization tokens."""
    if provider_id == "google_chat":
        gc_service.disconnect()
        return None

    elif provider_id == "gmail":
        gmail_service.disconnect()
        return None

    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown notification provider: {provider_id}",
        )
