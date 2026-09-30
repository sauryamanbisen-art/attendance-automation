"""Gmail API routes for OAuth 2.0 authorization."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.schemas import GmailAuthorizeResponse, GmailCallbackResponse
from app.config import Settings, get_settings
from app.database import get_db
from app.notifications.oauth import (
    OAuthAuthenticationError,
    OAuthConfigurationError,
)
from app.security.redaction import redact_string
from app.services.gmail_oauth_service import GmailOAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/gmail", tags=["OAuth", "Gmail"])


def get_gmail_oauth_service(settings: Settings = Depends(get_settings)) -> GmailOAuthService:
    """Dependency injection for GmailOAuthService."""
    return GmailOAuthService(settings=settings)


@router.get("/authorize", response_model=GmailAuthorizeResponse)
def authorize_gmail(
    request: Request,
    redirect: bool = Query(
        default=False,
        description="If True, returns a 307 redirect to Google authorization page; if False, returns JSON",
    ),
    prompt: str = Query(
        default="consent",
        description="OAuth prompt mode ('consent' forces approval screen for offline refresh token)",
    ),
    service: GmailOAuthService = Depends(get_gmail_oauth_service),
) -> Any:
    """Initiate OAuth 2.0 authorization flow for Gmail."""
    try:
        url, state = service.get_authorization_url(prompt=prompt)
    except OAuthConfigurationError as exc:
        safe_msg = redact_string(str(exc))
        logger.warning("Gmail OAuth configuration error on authorize: %s", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_msg,
        ) from exc

    if redirect:
        return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return GmailAuthorizeResponse(authorization_url=url, state=state)


@router.get("/callback", response_model=GmailCallbackResponse)
def gmail_oauth_callback(
    request: Request,
    code: Optional[str] = Query(default=None, description="Authorization code from Google"),
    state: Optional[str] = Query(default=None, description="CSRF state parameter returned by Google"),
    error: Optional[str] = Query(default=None, description="OAuth error code if authorization failed"),
    error_description: Optional[str] = Query(default=None, description="Human-readable error description"),
    redirect: Optional[bool] = Query(default=None, description="Override redirect behavior"),
    service: GmailOAuthService = Depends(get_gmail_oauth_service),
) -> Any:
    """Handle OAuth 2.0 callback from Google for Gmail."""
    accept_header = request.headers.get("accept", "")
    should_redirect = (
        redirect
        if redirect is not None
        else ("text/html" in accept_header and "application/json" not in accept_header)
    )

    try:
        token = service.handle_callback(
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )
        if should_redirect:
            return RedirectResponse(
                url="/#settings?oauth_success=gmail",
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )

        return GmailCallbackResponse(
            status="connected",
            message="Gmail OAuth authorization successful. Credentials stored securely.",
            scope=token.scope,
            expires_at=token.expires_at,
        )

    except OAuthAuthenticationError as exc:
        safe_msg = redact_string(str(exc))
        logger.warning("Gmail OAuth callback authentication failed: %s", safe_msg)
        if should_redirect:
            return RedirectResponse(
                url="/#settings?oauth_error=true",
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_msg,
        ) from exc
    except OAuthConfigurationError as exc:
        safe_msg = redact_string(str(exc))
        logger.error("Gmail OAuth configuration error during callback: %s", safe_msg)
        if should_redirect:
            return RedirectResponse(
                url="/#settings?oauth_error=true",
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_msg,
        ) from exc
    except Exception as exc:
        safe_msg = redact_string(str(exc))
        logger.error("Unexpected error in Gmail OAuth callback: %s", safe_msg)
        if should_redirect:
            return RedirectResponse(
                url="/#settings?oauth_error=true",
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred during OAuth authorization.",
        ) from exc


@router.get("/status")
def gmail_status(
    service: GmailOAuthService = Depends(get_gmail_oauth_service),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve connection status for Gmail without revealing secrets."""
    status_info = service.get_connection_status(db=db)
    if status_info.get("connected"):
        status_info["account_identifier"] = service.settings.notification_sender_email
    return status_info


@router.post("/disconnect")
def gmail_disconnect(
    service: GmailOAuthService = Depends(get_gmail_oauth_service),
) -> dict[str, str]:
    """Revoke local authorization by deleting stored tokens."""
    service.disconnect()
    return {
        "status": "disconnected",
        "message": "Gmail authorization credentials cleared successfully.",
    }
