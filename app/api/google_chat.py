"""Google Chat OAuth and Space configuration endpoints."""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.schemas import (
    DefaultSpaceUpdateRequest,
    DiscoverDmRequest,
    DiscoverDmResponse,
    GoogleChatAuthorizeResponse,
    GoogleChatCallbackResponse,
    GoogleChatStatusResponse,
    ProfessorSpaceMappingItem,
    SpaceMappingUpdateRequest,
)
from app.config import Settings, get_settings
from app.database import get_db
from app.notifications.google_chat.exceptions import (
    GoogleChatApiError,
    GoogleChatPermissionError,
    GoogleChatRateLimitError,
    GoogleChatRecipientError,
    OAuthAuthenticationError,
    OAuthConfigurationError,
)
from app.security.redaction import redact_string
from app.services.google_chat_oauth_service import (
    GoogleChatOAuthService,
    OAuthStateManager,
    get_oauth_state_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google-chat", tags=["Google Chat OAuth"])


def get_google_chat_service(
    settings: Settings = Depends(get_settings),
    state_manager: OAuthStateManager = Depends(get_oauth_state_manager),
) -> GoogleChatOAuthService:
    """Dependency provider for GoogleChatOAuthService."""
    return GoogleChatOAuthService(settings=settings, state_manager=state_manager)


@router.get("/authorize", response_model=GoogleChatAuthorizeResponse)
def google_chat_authorize(
    redirect: bool = Query(
        default=False,
        description="If True, returns a 307 redirect to Google authorization page; if False, returns JSON",
    ),
    prompt: str = Query(
        default="consent",
        description="OAuth prompt mode ('consent' forces approval screen for offline refresh token)",
    ),
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
) -> Any:
    """Initiate Google OAuth 2.0 authorization flow.

    Returns the Google authorization URL with a unique CSRF state parameter.
    If redirect=true, directly redirects the user's browser.
    """
    try:
        url, state = service.get_authorization_url(prompt=prompt)
    except OAuthConfigurationError as exc:
        safe_msg = redact_string(str(exc))
        logger.warning("Authorize request failed due to missing configuration: %s", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_msg,
        )

    if redirect:
        return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return GoogleChatAuthorizeResponse(authorization_url=url, state=state)


@router.get("/callback", response_model=GoogleChatCallbackResponse)
def google_chat_callback(
    request: Request,
    code: Optional[str] = Query(default=None, description="Authorization code from Google"),
    state: Optional[str] = Query(default=None, description="CSRF state parameter returned by Google"),
    error: Optional[str] = Query(default=None, description="OAuth error code if authorization failed"),
    error_description: Optional[str] = Query(default=None, description="Human-readable error description"),
    redirect: Optional[bool] = Query(default=None, description="Override redirect behavior"),
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
) -> Any:
    """Handle Google OAuth 2.0 redirect callback.

    Validates the CSRF state token and exchanges the authorization code for access
    and refresh tokens. Credentials are saved locally with restricted permissions.
    """
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
                url="/#settings?oauth_success=google_chat",
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )

        return GoogleChatCallbackResponse(
            status="connected",
            message="Google Chat OAuth authorization successful. Credentials stored securely.",
            scope=token.scope,
            expires_at=token.expires_at,
        )
    except OAuthAuthenticationError as exc:
        safe_msg = redact_string(str(exc))
        logger.warning("Google Chat OAuth callback authentication failed: %s", safe_msg)
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
        logger.error("Google Chat OAuth configuration error during callback: %s", safe_msg)
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
        logger.error("Unexpected error during Google Chat OAuth callback: %s", safe_msg)
        if should_redirect:
            return RedirectResponse(
                url="/#settings?oauth_error=true",
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred during OAuth authorization.",
        ) from exc


@router.get("/status", response_model=GoogleChatStatusResponse)
def google_chat_status(
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
    db: Session = Depends(get_db),
) -> GoogleChatStatusResponse:
    """Retrieve connection and space status for Google Chat without revealing secrets."""
    status_info = service.get_connection_status(db=db)
    return GoogleChatStatusResponse(**status_info)


@router.post("/disconnect")
def google_chat_disconnect(
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
) -> dict[str, str]:
    """Revoke local authorization by deleting stored tokens."""
    service.disconnect()
    return {
        "status": "disconnected",
        "message": "Google Chat authorization credentials cleared successfully.",
    }


@router.get("/spaces")
def list_spaces(
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all subjects with their assigned professors and Google Chat spaces."""
    default_space = service.get_effective_default_space(db=db)
    mappings = service.get_professor_spaces(db=db)
    return {
        "default_space": default_space,
        "mappings": mappings,
    }


@router.put("/spaces/{subject_code}", response_model=ProfessorSpaceMappingItem)
def update_space_mapping(
    subject_code: str,
    payload: SpaceMappingUpdateRequest,
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
    db: Session = Depends(get_db),
) -> ProfessorSpaceMappingItem:
    """Update or clear the Google Chat space for a specific subject's professor."""
    try:
        updated = service.update_professor_space(
            db=db,
            subject_code=subject_code,
            google_chat_space=payload.google_chat_space,
        )
        return ProfessorSpaceMappingItem(**updated)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put("/default-space")
def update_default_space(
    payload: DefaultSpaceUpdateRequest,
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update or clear the fallback default Google Chat space."""
    new_default = service.set_default_space(db=db, default_space=payload.default_space)
    return {
        "status": "updated",
        "default_space": new_default,
    }


def _handle_discover_error(exc: Exception, identifier: str) -> None:
    """Map domain exceptions from DM discovery to security-safe HTTP responses."""
    safe_msg = redact_string(str(exc))
    if isinstance(exc, OAuthConfigurationError):
        logger.warning("Google Chat DM discovery failed: OAuth not configured (%s)", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Chat OAuth is not configured. Please configure credentials in Settings or .env file.",
        )
    elif isinstance(exc, OAuthAuthenticationError):
        logger.warning("Google Chat DM discovery failed: Authentication error (%s)", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google Chat OAuth is not connected or token expired. Please connect Google Chat in Settings.",
        )
    elif isinstance(exc, GoogleChatPermissionError):
        logger.warning("Google Chat DM discovery failed: Permission/scope denied (%s)", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Google Chat permission denied. The connected account lacks the required OAuth scope "
                "('https://www.googleapis.com/auth/chat.spaces.readonly'). Please reconnect Google Chat in Settings."
            ),
        )
    elif isinstance(exc, GoogleChatRecipientError):
        logger.info("Google Chat DM discovery recipient error for %s: %s", redact_string(identifier), safe_msg)
        if "No direct message space exists" in safe_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=safe_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_msg,
        )
    elif isinstance(exc, GoogleChatRateLimitError):
        logger.warning("Google Chat DM discovery rate limited: %s", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Google Chat API rate limit exceeded. Please try again shortly.",
        )
    elif isinstance(exc, GoogleChatApiError):
        logger.error("Google Chat DM discovery API error: %s", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Chat API request failed: {safe_msg}",
        )
    elif isinstance(exc, KeyError):
        logger.warning("Google Chat DM discovery target not found: %s", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=safe_msg,
        )
    elif isinstance(exc, ValueError):
        logger.warning("Google Chat DM discovery validation error: %s", safe_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_msg,
        )
    else:
        logger.error("Unexpected error during Google Chat DM discovery: %s", safe_msg, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while discovering the Google Chat space.",
        )


@router.post("/discover-dm", response_model=DiscoverDmResponse)
def discover_direct_message(
    payload: DiscoverDmRequest,
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
    db: Session = Depends(get_db),
) -> DiscoverDmResponse:
    """Discover existing Google Chat DM space for a professor email.

    Uses Google Chat API findDirectMessage and user's OAuth credentials.
    If subject_code is provided or professor mapping exists, saves the space in the database.
    """
    try:
        result = service.discover_professor_dm(
            db=db,
            professor_email=payload.professor_email,
            subject_code=payload.subject_code,
        )
        return DiscoverDmResponse(**result)
    except Exception as exc:
        _handle_discover_error(exc, payload.professor_email)


@router.post("/spaces/{subject_code}/discover", response_model=DiscoverDmResponse)
def discover_subject_space(
    subject_code: str,
    professor_email: Optional[str] = Query(default=None, description="Optional override professor email"),
    service: GoogleChatOAuthService = Depends(get_google_chat_service),
    db: Session = Depends(get_db),
) -> DiscoverDmResponse:
    """Auto-discover and configure the Google Chat DM space for a subject's assigned professor."""
    try:
        result = service.discover_and_update_professor_space(
            db=db,
            subject_code=subject_code,
            professor_email=professor_email,
        )
        return DiscoverDmResponse(**result)
    except Exception as exc:
        _handle_discover_error(exc, subject_code)
