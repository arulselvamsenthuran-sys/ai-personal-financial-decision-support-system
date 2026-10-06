"""Authentication and session management service."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import uuid

from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    validate_password_policy,
    verify_password,
)
from app.models.profile import UserProfile
from app.models.session import Session as AuthSession
from app.models.user import User

logger = get_logger(__name__)

# Precomputed dummy hash to defend against timing-based user enumeration attacks
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$2q1z4y6H8j0l1n3p5r7t9v"
    "$w9kL4r2X1y3z5A7b9c1d3e5f7g9h1i3j5k7l9m1n3o"
)


def register_user(db: DbSession, email: str, password: str) -> User:
    """Register a new user with Argon2id hashed password and initialize profile.

    Raises:
        AppError(422): If password policy fails.
        AppError(409): If email is already registered.
    """
    normalized_email = email.strip().lower()

    # Enforce password policy
    is_valid, error_message = validate_password_policy(password)
    if not is_valid:
        raise AppError(message=error_message, status_code=422)

    # Check email uniqueness
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user:
        logger.info("Registration attempt with existing email: %s", normalized_email)
        raise AppError(
            message="An account with this email address already exists.",
            status_code=409,
        )

    # Hash password with Argon2id
    pwd_hash = hash_password(password)

    # Create User and associated initial UserProfile in a single transaction
    user = User(
        email=normalized_email,
        password_hash=pwd_hash,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.flush()  # Populates user.id

    profile = UserProfile(
        user_id=user.id,
        display_name=normalized_email.split("@")[0],
        preferred_currency="USD",
        timezone="UTC",
    )
    db.add(profile)
    db.commit()
    db.refresh(user)

    logger.info("User registered successfully: id=%s", user.id)
    return user


def authenticate_user(db: DbSession, email: str, password: str) -> User:
    """Authenticate a user using email and password.

    Uses dummy hash evaluation when user is not found to defend against
    timing-based user enumeration.

    Raises:
        AppError(401): If credentials are invalid.
        AppError(403): If user account is disabled.
    """
    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()

    if not user or not user.password_hash:
        # Prevent timing side-channels by performing verification on dummy hash
        verify_password(password, _DUMMY_HASH)
        raise AppError(message="Invalid email or password.", status_code=401)

    if not verify_password(password, user.password_hash):
        raise AppError(message="Invalid email or password.", status_code=401)

    if not user.is_active:
        logger.warning("Authentication attempt for inactive user: id=%s", user.id)
        raise AppError(message="Account is inactive.", status_code=403)

    return user


def create_session(db: DbSession, user_id: uuid.UUID) -> Tuple[str, AuthSession]:
    """Create a server-side session in PostgreSQL.

    Returns:
        (raw_token, session_record): The raw token is sent only in the HttpOnly cookie.
        The database stores strictly the SHA-256 hash.
    """
    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.session_max_age_seconds
    )

    session = AuthSession(
        user_id=user_id,
        session_token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info("Session created: id=%s for user_id=%s", session.id, user_id)
    return raw_token, session


def validate_session(db: DbSession, raw_token: Optional[str]) -> Optional[User]:
    """Validate a raw session token and return the associated active user.

    Returns None if token is invalid, expired, or revoked.
    """
    if not raw_token:
        return None

    token_hash = hash_session_token(raw_token)
    session = (
        db.query(AuthSession)
        .filter(AuthSession.session_token_hash == token_hash)
        .first()
    )

    if not session:
        return None

    # Check explicit revocation
    if session.revoked_at is not None:
        return None

    # Check server-side expiration
    now = datetime.now(timezone.utc)
    if session.expires_at <= now:
        return None

    # Check user existence and activity
    if not session.user or not session.user.is_active:
        return None

    return session.user


def revoke_session(db: DbSession, raw_token: Optional[str]) -> bool:
    """Revoke an active session by token hash.

    Sets revoked_at timestamp in the database.
    """
    if not raw_token:
        return False

    token_hash = hash_session_token(raw_token)
    session = (
        db.query(AuthSession)
        .filter(AuthSession.session_token_hash == token_hash)
        .first()
    )

    if not session:
        return False

    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Session revoked: id=%s", session.id)

    return True
