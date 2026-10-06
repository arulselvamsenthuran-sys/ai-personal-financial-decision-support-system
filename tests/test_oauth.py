"""Phase 5 OAuth 2.0 integration & security tests.

Tests:
1. Google OAuth authorization URL generation & state creation.
2. Facebook OAuth authorization URL generation.
3. Google OAuth callback (successful login & session creation).
4. Facebook OAuth callback (successful login & session creation).
5. Existing linked OAuth account login.
6. Invalid/expired state parameter rejection (HTTP 400).
7. Invalid authorization code handling (HTTP 400).
8. Manual account linking to authenticated user.
9. Preventing duplicate provider-account mappings (HTTP 409).
10. OAuth session revocation on logout.
11. Unified /api/auth/me behavior across native and OAuth session logins.
"""

from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, patch
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import auth_rate_limiter
from app.db.session import SessionLocal
from app.main import app
from app.models.oauth import OAuthAccount
from app.models.user import User
from app.services.oauth_service import generate_oauth_state


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Yield a database session and clean up created records after test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient fixture with reset rate limiter."""
    auth_rate_limiter.reset()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
        follow_redirects=True,
    ) as ac:
        yield ac


# ============================================================================
# 1. Authorization URL Generation & State Verification
# ============================================================================
@pytest.mark.anyio
async def test_get_oauth_url_google_and_facebook(client: AsyncClient):
    """Verify authorization URL endpoint returns valid URL and state for Google and Facebook."""
    resp_google = await client.get("/api/auth/oauth/google/url")
    assert resp_google.status_code == 200
    data_g = resp_google.json()
    assert "accounts.google.com" in data_g["authorization_url"]
    assert "state=" in data_g["authorization_url"]
    assert data_g["state"] != ""

    resp_fb = await client.get("/api/auth/oauth/facebook/url")
    assert resp_fb.status_code == 200
    data_fb = resp_fb.json()
    assert "facebook.com" in data_fb["authorization_url"]
    assert "state=" in data_fb["authorization_url"]


# ============================================================================
# 2. Google OAuth Callback Success & Session Creation
# ============================================================================
@pytest.mark.anyio
@patch("app.api.oauth.fetch_provider_user_profile", new_callable=AsyncMock)
async def test_google_oauth_callback_success(mock_fetch_profile, client: AsyncClient, db: Session):
    """Verify Google OAuth callback provisions new user, links oauth_account, and issues session cookie."""
    g_id = f"google_id_{uuid.uuid4().hex[:8]}"
    email = f"google_user_{uuid.uuid4().hex[:8]}@gmail.com"
    mock_fetch_profile.return_value = {
        "provider_user_id": g_id,
        "email": email,
        "display_name": "Google Tester",
    }

    state = generate_oauth_state("google")
    resp = await client.post(
        "/api/auth/oauth/google/callback",
        json={"code": "valid_google_code_123", "state": state},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == email
    assert settings.session_cookie_name in resp.cookies

    # Verify database records
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    oauth_acc = db.query(OAuthAccount).filter(OAuthAccount.user_id == user.id).first()
    assert oauth_acc is not None
    assert oauth_acc.provider == "google"
    assert oauth_acc.provider_user_id == g_id

    # Verify /api/auth/me works seamlessly
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["id"] == str(user.id)

    # Cleanup
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    db.commit()


# ============================================================================
# 3. Facebook OAuth Callback Success
# ============================================================================
@pytest.mark.anyio
@patch("app.api.oauth.fetch_provider_user_profile", new_callable=AsyncMock)
async def test_facebook_oauth_callback_success(mock_fetch_profile, client: AsyncClient, db: Session):
    """Verify Facebook OAuth callback logs in user cleanly."""
    fb_id = f"fb_id_{uuid.uuid4().hex[:8]}"
    email = f"fb_user_{uuid.uuid4().hex[:8]}@example.com"
    mock_fetch_profile.return_value = {
        "provider_user_id": fb_id,
        "email": email,
        "display_name": "Facebook Tester",
    }

    state = generate_oauth_state("facebook")
    resp = await client.post(
        "/api/auth/oauth/facebook/callback",
        json={"code": "valid_fb_code_123", "state": state},
    )

    assert resp.status_code == 200
    assert resp.json()["email"] == email

    user = db.query(User).filter(User.email == email).first()
    assert user is not None

    # Cleanup
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    db.commit()


# ============================================================================
# 4. Invalid State Parameter Rejection
# ============================================================================
@pytest.mark.anyio
async def test_oauth_callback_invalid_state_fails(client: AsyncClient):
    """Verify forged or corrupted state parameter returns HTTP 400 Bad Request."""
    invalid_state = "invalid:forged_nonce:1234567:bad_signature"
    resp = await client.post(
        "/api/auth/oauth/google/callback",
        json={"code": "some_code", "state": invalid_state},
    )
    assert resp.status_code == 400
    assert "invalid or expired" in resp.json()["detail"].lower()


# ============================================================================
# 5. Account Linking Security Tests
# ============================================================================
@pytest.mark.anyio
@patch("app.api.oauth.fetch_provider_user_profile", new_callable=AsyncMock)
async def test_manual_account_linking_success(mock_fetch_profile, client: AsyncClient, db: Session):
    """Verify authenticated user can manually link Google account."""
    email = f"native_user_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "Password123!"

    # 1. Register & login native user
    await client.post("/api/auth/register", json={"email": email, "password": pwd})
    login_resp = await client.post("/api/auth/login", json={"email": email, "password": pwd})
    user_id = login_resp.json()["id"]

    # 2. Link Google account
    g_id = f"google_link_{uuid.uuid4().hex[:8]}"
    mock_fetch_profile.return_value = {
        "provider_user_id": g_id,
        "email": email,
        "display_name": "Linked Google Account",
    }

    state = generate_oauth_state("google")
    link_resp = await client.post(
        "/api/auth/oauth/google/link",
        json={"code": "code_link_123", "state": state},
    )
    assert link_resp.status_code == 200

    # 3. Verify linkage in DB
    oauth_acc = db.query(OAuthAccount).filter(OAuthAccount.provider_user_id == g_id).first()
    assert oauth_acc is not None
    assert str(oauth_acc.user_id) == user_id

    # Cleanup
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": uuid.UUID(user_id)})
    db.commit()


# ============================================================================
# 6. Prevent Duplicate Provider Account Linkage
# ============================================================================
@pytest.mark.anyio
@patch("app.services.oauth_service.fetch_provider_user_profile", new_callable=AsyncMock)
async def test_duplicate_provider_account_mapping_fails(mock_fetch_profile, client: AsyncClient, db: Session):
    """Verify an OAuth identity already linked to User A cannot be linked to User B."""
    g_id = f"google_dup_{uuid.uuid4().hex[:8]}"
    mock_fetch_profile.return_value = {"provider_user_id": g_id, "email": "a@example.com"}

    # User A registers & logs in
    r1 = await client.post("/api/auth/register", json={"email": f"usera_{uuid.uuid4().hex[:6]}@example.com", "password": "Password123!"})
    user_a = db.query(User).filter(User.id == uuid.UUID(r1.json()["id"])).first()

    from app.services.oauth_service import link_oauth_account_to_user
    link_oauth_account_to_user(db=db, user=user_a, provider="google", provider_user_id=g_id)

    # User B attempts to link same Google ID -> Must fail with HTTP 409 Conflict
    user_b = User(email=f"userb_{uuid.uuid4().hex[:6]}@example.com", is_active=True)
    db.add(user_b)
    db.commit()

    from app.core.errors import AppError
    with pytest.raises(AppError) as exc_info:
        link_oauth_account_to_user(db=db, user=user_b, provider="google", provider_user_id=g_id)
    assert exc_info.value.status_code == 409

    # Cleanup
    db.execute(text("DELETE FROM users WHERE id IN (:id_a, :id_b)"), {"id_a": user_a.id, "id_b": user_b.id})
    db.commit()


# ============================================================================
# 7. Session Revocation on Logout for OAuth Users
# ============================================================================
@pytest.mark.anyio
@patch("app.api.oauth.fetch_provider_user_profile", new_callable=AsyncMock)
async def test_oauth_session_revocation_on_logout(mock_fetch_profile, client: AsyncClient, db: Session):
    """Verify logging out revokes the session created via OAuth login."""
    email = f"oauth_logout_{uuid.uuid4().hex[:8]}@example.com"
    mock_fetch_profile.return_value = {"provider_user_id": "oauth_rev_123", "email": email}

    state = generate_oauth_state("google")
    await client.post("/api/auth/oauth/google/callback", json={"code": "code", "state": state})

    # Logout
    logout_resp = await client.post("/api/auth/logout")
    assert logout_resp.status_code == 200

    # /api/auth/me should fail with 401
    me_resp = await client.get("/api/auth/me")
    assert me_resp.status_code == 401

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()
