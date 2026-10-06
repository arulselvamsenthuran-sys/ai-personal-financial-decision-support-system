"""OAuth 2.0 authentication service for Google and Facebook."""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Dict, Optional, Tuple
import uuid

import httpx
from sqlalchemy.orm import Session as DbSession

from app.core.audit import audit_log
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.oauth import OAuthAccount
from app.models.profile import UserProfile
from app.models.user import User

logger = get_logger(__name__)


def generate_oauth_state(provider: str) -> str:
    """Generate a signed cryptographic state token to prevent CSRF in OAuth flows."""
    nonce = secrets.token_urlsafe(16)
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    payload = f"{provider}:{nonce}:{timestamp}"
    
    signature = hmac.new(
        settings.oauth_state_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    
    return f"{payload}:{signature}"


def verify_oauth_state(state: str, expected_provider: str) -> bool:
    """Verify cryptographic signature and age of OAuth state parameter."""
    try:
        parts = state.split(":")
        if len(parts) != 4:
            return False
            
        provider, nonce, timestamp_str, signature = parts
        if provider != expected_provider:
            return False

        # Verify state signature
        payload = f"{provider}:{nonce}:{timestamp_str}"
        expected_signature = hmac.new(
            settings.oauth_state_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not secrets.compare_digest(signature, expected_signature):
            return False

        # Check timestamp expiration (10 minutes)
        timestamp = int(timestamp_str)
        now = int(datetime.now(timezone.utc).timestamp())
        if now - timestamp > 600 or timestamp > now + 60:
            return False

        return True
    except Exception:
        return False


def get_oauth_authorization_url(provider: str, state: str) -> str:
    """Build authorization URL for target OAuth provider."""
    if provider == "google":
        base_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    elif provider == "facebook":
        base_url = "https://www.facebook.com/v18.0/dialog/oauth"
        params = {
            "client_id": settings.facebook_client_id,
            "redirect_uri": settings.facebook_redirect_uri,
            "response_type": "code",
            "scope": "email,public_profile",
            "state": state,
        }
    else:
        raise AppError(message=f"Unsupported OAuth provider: {provider}", status_code=400)

    return f"{base_url}?{httpx.QueryParams(params)}"


async def fetch_provider_user_profile(provider: str, code: str) -> Dict[str, str]:
    """Exchange authorization code for provider user identity.

    Returns dict with keys: 'provider_user_id', 'email' (optional), 'display_name' (optional).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        if provider == "google":
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.google_redirect_uri,
                },
            )
            if token_resp.status_code != 200:
                logger.error("Google token exchange failed: %s", token_resp.text)
                raise AppError(message="Failed to exchange authorization code with Google.", status_code=400)
            
            token_data = token_resp.json()
            access_token = token_data.get("access_token")

            user_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if user_resp.status_code != 200:
                raise AppError(message="Failed to retrieve profile from Google.", status_code=400)
            
            user_info = user_resp.json()
            return {
                "provider_user_id": str(user_info["id"]),
                "email": user_info.get("email"),
                "display_name": user_info.get("name"),
            }

        elif provider == "facebook":
            token_resp = await client.get(
                "https://graph.facebook.com/v18.0/oauth/access_token",
                params={
                    "client_id": settings.facebook_client_id,
                    "client_secret": settings.facebook_client_secret,
                    "redirect_uri": settings.facebook_redirect_uri,
                    "code": code,
                },
            )
            if token_resp.status_code != 200:
                logger.error("Facebook token exchange failed: %s", token_resp.text)
                raise AppError(message="Failed to exchange authorization code with Facebook.", status_code=400)

            token_data = token_resp.json()
            access_token = token_data.get("access_token")

            user_resp = await client.get(
                "https://graph.facebook.com/v18.0/me",
                params={
                    "fields": "id,name,email",
                    "access_token": access_token,
                },
            )
            if user_resp.status_code != 200:
                raise AppError(message="Failed to retrieve profile from Facebook.", status_code=400)

            user_info = user_resp.json()
            return {
                "provider_user_id": str(user_info["id"]),
                "email": user_info.get("email"),
                "display_name": user_info.get("name"),
            }
        else:
            raise AppError(message=f"Unsupported OAuth provider: {provider}", status_code=400)


def authenticate_or_create_oauth_user(
    db: DbSession,
    provider: str,
    provider_user_id: str,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
) -> User:
    """Authenticate or provision an internal user identity for an OAuth profile.

    1. Check existing oauth_accounts record by (provider, provider_user_id).
    2. If exists -> Return linked User.
    3. If not exists -> Create new internal User and link OAuthAccount.
    """
    oauth_acc = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
        .first()
    )

    if oauth_acc:
        logger.info("OAuth login for existing linked user: id=%s", oauth_acc.user_id)
        return oauth_acc.user

    # No existing OAuth link exists. Create a new internal User record.
    user_email = email.strip().lower() if email else f"{provider}_{provider_user_id}@oauth.local"

    # Ensure unique email to avoid collision
    existing_user = db.query(User).filter(User.email == user_email).first()
    if existing_user:
        # Check if already has OAuth linked
        user = existing_user
    else:
        user = User(
            email=user_email,
            password_hash=None,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.flush()

        profile = UserProfile(
            user_id=user.id,
            display_name=display_name or user_email.split("@")[0],
            preferred_currency="USD",
            timezone="UTC",
        )
        db.add(profile)

    # Link OAuth account
    new_oauth_link = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
    )
    db.add(new_oauth_link)
    db.commit()
    db.refresh(user)

    logger.info("New OAuth user created/linked: user_id=%s, provider=%s", user.id, provider)
    return user


def link_oauth_account_to_user(
    db: DbSession,
    user: User,
    provider: str,
    provider_user_id: str,
) -> OAuthAccount:
    """Manually link an OAuth identity to an authenticated existing user."""
    # Check if this provider identity is already linked to any user
    existing_link = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
        .first()
    )

    if existing_link:
        if existing_link.user_id == user.id:
            return existing_link
        audit_log(
            event_type="OAUTH_LINK_FAILED",
            user_id=user.id,
            status="BLOCKED",
            details={"reason": "Provider account already linked to another user", "provider": provider},
        )
        raise AppError(
            message="This OAuth account is already linked to another user account.",
            status_code=409,
        )

    link = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    audit_log(
        event_type="OAUTH_LINK_SUCCESS",
        user_id=user.id,
        status="SUCCESS",
        details={"provider": provider},
    )
    return link
