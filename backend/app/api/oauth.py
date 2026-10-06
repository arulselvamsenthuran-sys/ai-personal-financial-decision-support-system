"""OAuth API endpoints for Google and Facebook authorization flows."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.config import settings
from app.core.csrf import verify_csrf
from app.core.rate_limit import check_rate_limit
from app.models.user import User
from app.schemas.auth import UserResponse
from app.services.auth_service import create_session
from app.services.oauth_service import (
    authenticate_or_create_oauth_user,
    fetch_provider_user_profile,
    generate_oauth_state,
    get_oauth_authorization_url,
    link_oauth_account_to_user,
    verify_oauth_state,
)

router = APIRouter(prefix="/api/auth/oauth", tags=["OAuth Authentication"])


class OAuthUrlResponse(BaseModel):
    authorization_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class OAuthLinkRequest(BaseModel):
    code: str
    state: str


@router.get(
    "/{provider}/url",
    response_model=OAuthUrlResponse,
    dependencies=[Depends(check_rate_limit)],
    summary="Get OAuth authorization URL",
    description="Generates provider authorization URL and signed state token for Google or Facebook.",
)
def get_oauth_url(provider: str) -> OAuthUrlResponse:
    """Generate provider authorization URL and signed state."""
    if provider not in ("google", "facebook"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider: {provider}",
        )

    state = generate_oauth_state(provider)
    url = get_oauth_authorization_url(provider, state)
    return OAuthUrlResponse(authorization_url=url, state=state)


@router.post(
    "/{provider}/callback",
    response_model=UserResponse,
    dependencies=[Depends(check_rate_limit)],
    summary="OAuth callback handler",
    description="Exchanges authorization code for user identity, creates server-side session, and sets cookie.",
)
async def oauth_callback(
    provider: str,
    payload: OAuthCallbackRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Exchange authorization code and log in user via secure server-side session."""
    if provider not in ("google", "facebook"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider: {provider}",
        )

    # 1. Verify state parameter signature and timestamp
    if not verify_oauth_state(payload.state, expected_provider=provider):
        audit_log(
            event_type="OAUTH_CALLBACK_FAILED",
            status="BLOCKED",
            details={"reason": "Invalid or expired state parameter", "provider": provider},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state parameter.",
        )

    # 2. Exchange authorization code for user profile
    profile_data = await fetch_provider_user_profile(provider, payload.code)

    # 3. Authenticate or provision internal User
    user = authenticate_or_create_oauth_user(
        db=db,
        provider=provider,
        provider_user_id=profile_data["provider_user_id"],
        email=profile_data.get("email"),
        display_name=profile_data.get("display_name"),
    )

    # 4. Create standard application server-side session
    raw_token, _ = create_session(db=db, user_id=user.id)

    # 5. Issue session cookie
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        domain=settings.session_cookie_domain,
        path=settings.session_cookie_path,
    )

    client_ip = request.client.host if request.client else None
    audit_log(
        event_type="OAUTH_LOGIN_SUCCESS",
        user_id=user.id,
        status="SUCCESS",
        ip_address=client_ip,
        details={"provider": provider},
    )

    return UserResponse.model_validate(user)


@router.post(
    "/{provider}/link",
    dependencies=[Depends(verify_csrf)],
    summary="Link OAuth account to current user",
    description="Manually links a Google or Facebook account to an authenticated existing user.",
)
async def link_oauth_account(
    provider: str,
    payload: OAuthLinkRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Link OAuth provider identity to currently authenticated user."""
    if provider not in ("google", "facebook"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider: {provider}",
        )

    if not verify_oauth_state(payload.state, expected_provider=provider):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state parameter.",
        )

    profile_data = await fetch_provider_user_profile(provider, payload.code)
    link = link_oauth_account_to_user(
        db=db,
        user=current_user,
        provider=provider,
        provider_user_id=profile_data["provider_user_id"],
    )

    return {"detail": f"Successfully linked {provider} account.", "provider": link.provider}
