"""Authentication API endpoints."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.config import settings
from app.core.csrf import verify_csrf
from app.core.rate_limit import check_rate_limit
from app.models.user import User
from app.schemas.auth import (
    MessageResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.auth_service import (
    authenticate_user,
    create_session,
    register_user,
    revoke_session,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(check_rate_limit)],
    summary="User registration",
    description="Registers a new user account with an Argon2id hashed password.",
)
def register(
    payload: UserRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Register a new user account."""
    client_ip = request.client.host if request.client else None
    try:
        user = register_user(db=db, email=payload.email, password=payload.password)
        audit_log(
            event_type="REGISTER_SUCCESS",
            user_id=user.id,
            status="SUCCESS",
            ip_address=client_ip,
            details={"email": payload.email},
        )
        return UserResponse.model_validate(user)
    except Exception:
        audit_log(
            event_type="REGISTER_FAILURE",
            status="FAILURE",
            ip_address=client_ip,
            details={"email": payload.email},
        )
        raise


@router.post(
    "/login",
    response_model=UserResponse,
    dependencies=[Depends(check_rate_limit)],
    summary="User login",
    description="Authenticates credentials, creates a server-side session, and sets an HttpOnly cookie.",
)
def login(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Authenticate user and issue a secure session cookie."""
    client_ip = request.client.host if request.client else None
    try:
        user = authenticate_user(db=db, email=payload.email, password=payload.password)
        raw_token, _ = create_session(db=db, user_id=user.id)

        # Set secure HttpOnly session cookie
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

        audit_log(
            event_type="LOGIN_SUCCESS",
            user_id=user.id,
            status="SUCCESS",
            ip_address=client_ip,
        )
        return UserResponse.model_validate(user)
    except Exception:
        audit_log(
            event_type="LOGIN_FAILURE",
            status="FAILURE",
            ip_address=client_ip,
            details={"email": payload.email},
        )
        raise


@router.post(
    "/logout",
    response_model=MessageResponse,
    dependencies=[Depends(verify_csrf)],
    summary="User logout",
    description="Revokes the active server-side session and clears the session cookie.",
)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Log out by invalidating the session in PostgreSQL and clearing the cookie."""
    client_ip = request.client.host if request.client else None
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        revoke_session(db=db, raw_token=raw_token)

    response.delete_cookie(
        key=settings.session_cookie_name,
        path=settings.session_cookie_path,
        domain=settings.session_cookie_domain,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )

    audit_log(
        event_type="LOGOUT",
        status="SUCCESS",
        ip_address=client_ip,
    )
    return MessageResponse(detail="Successfully logged out.")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current authenticated user",
    description="Returns the profile of the user associated with the active session cookie.",
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated user's safe identity details."""
    return UserResponse.model_validate(current_user)

