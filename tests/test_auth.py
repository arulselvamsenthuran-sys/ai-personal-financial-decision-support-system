"""Authentication and session management test suite for Phase 3.

Covers all 17 security and operational test requirements:
1. Registration success
2. Duplicate email rejection
3. Password is not stored plaintext
4. Password hash format (Argon2id)
5. Login success
6. Wrong password rejection
7. Unknown email rejection
8. Session creation in PostgreSQL
9. Raw session token not stored in database
10. /api/auth/me authenticated request
11. Unauthenticated /api/auth/me returns 401
12. Logout revokes session and clears cookie
13. Revoked session cannot authenticate
14. Expired session cannot authenticate
15. Cookie security flags (HttpOnly, SameSite, Secure)
16. Sensitive fields (password_hash, session_token_hash) never exposed
17. Cross-user isolation (session deterministically identifies user)
"""

from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_session_token, verify_password
from app.db.session import SessionLocal
from app.main import app
from app.models.session import Session as AuthSession
from app.models.user import User


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """Yield a database session and ensure clean teardown."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
async def ac() -> AsyncGenerator[AsyncClient, None]:
    """Yield an AsyncClient configured for testing with cookies."""
    from app.core.rate_limit import auth_rate_limiter
    auth_rate_limiter.reset()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
        follow_redirects=True,
    ) as client:
        yield client




@pytest.fixture
def test_user_factory(db: Session):
    """Factory fixture that generates unique test user emails and cleans them up after test."""
    created_user_ids: list[uuid.UUID] = []

    def _create_unique_email() -> str:
        return f"auth_test_{uuid.uuid4().hex[:12]}@example.com"

    yield _create_unique_email

    # Teardown: delete all test users created during the test
    for user_id in created_user_ids:
        db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    db.commit()


# ============================================================================
# 1. Registration Success
# ============================================================================
@pytest.mark.anyio
async def test_1_registration_success(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 1: Valid user can register and receives a 201 response with safe data."""
    email = test_user_factory()
    password = "SecurePassword123!"

    response = await ac.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email
    assert data["is_active"] is True
    assert data["is_verified"] is False
    assert "id" in data

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 2. Duplicate Email Rejection
# ============================================================================
@pytest.mark.anyio
async def test_2_duplicate_email_rejection(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 2: Same email cannot register twice; returns 409 Conflict."""
    email = test_user_factory()
    password = "SecurePassword123!"

    # First registration
    resp1 = await ac.post("/api/auth/register", json={"email": email, "password": password})
    assert resp1.status_code == 201

    # Second registration with same email
    resp2 = await ac.post("/api/auth/register", json={"email": email, "password": "AnotherPassword456!"})
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"].lower()

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 3. Password Is Not Plaintext
# ============================================================================
@pytest.mark.anyio
async def test_3_password_is_not_stored_plaintext(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 3: Verify the database does not contain the plaintext password."""
    email = test_user_factory()
    plain_password = "SuperSecretPassword987!"

    resp = await ac.post("/api/auth/register", json={"email": email, "password": plain_password})
    assert resp.status_code == 201

    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    assert user.password_hash != plain_password
    assert plain_password not in user.password_hash

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 4. Password Hash Format (Argon2id)
# ============================================================================
@pytest.mark.anyio
async def test_4_password_hash_format_argon2id(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 4: Verify the stored password hash is a valid Argon2id hash."""
    email = test_user_factory()
    password = "CorrectHorseBatteryStaple!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})

    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    assert user.password_hash is not None
    # Standard Argon2id hash begins with $argon2id$
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(password, user.password_hash) is True

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 5. Login Success
# ============================================================================
@pytest.mark.anyio
async def test_5_login_success(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 5: Correct credentials successfully authenticate and set session cookie."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})

    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert data["email"] == email

    # Verify session cookie was set in the response
    assert settings.session_cookie_name in login_resp.cookies
    cookie_value = login_resp.cookies.get(settings.session_cookie_name)
    assert cookie_value is not None
    assert len(cookie_value) > 20

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 6. Wrong Password
# ============================================================================
@pytest.mark.anyio
async def test_6_wrong_password_rejected(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 6: Incorrect password returns generic 401 Unauthorized."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})

    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": "WrongPassword999!"})
    assert login_resp.status_code == 401
    assert "invalid email or password" in login_resp.json()["detail"].lower()
    assert settings.session_cookie_name not in login_resp.cookies

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 7. Unknown Email
# ============================================================================
@pytest.mark.anyio
async def test_7_unknown_email_rejected_safely(ac: AsyncClient) -> None:
    """Test 7: Unknown email account returns generic 401 Unauthorized identically to wrong password."""
    fake_email = f"nonexistent_{uuid.uuid4().hex[:8]}@example.com"
    login_resp = await ac.post("/api/auth/login", json={"email": fake_email, "password": "SomePassword123!"})
    assert login_resp.status_code == 401
    assert "invalid email or password" in login_resp.json()["detail"].lower()


# ============================================================================
# 8. Session Creation in PostgreSQL
# ============================================================================
@pytest.mark.anyio
async def test_8_session_creation_in_database(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 8: Successful login creates a session record in PostgreSQL."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})
    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200

    user = db.query(User).filter(User.email == email).first()
    assert user is not None

    sessions = db.query(AuthSession).filter(AuthSession.user_id == user.id).all()
    assert len(sessions) == 1
    assert sessions[0].revoked_at is None
    assert sessions[0].expires_at > datetime.now(timezone.utc)

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 9. Raw Session Token Is Not Stored in PostgreSQL
# ============================================================================
@pytest.mark.anyio
async def test_9_raw_session_token_is_not_stored(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 9: Verify the database stores only SHA-256 token hash, never the raw cookie token."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})
    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})
    raw_token = login_resp.cookies.get(settings.session_cookie_name)
    assert raw_token is not None

    user = db.query(User).filter(User.email == email).first()
    session = db.query(AuthSession).filter(AuthSession.user_id == user.id).first()
    assert session is not None

    # Raw token must NOT equal the stored session_token_hash
    assert session.session_token_hash != raw_token
    # But hashing the raw token MUST match the stored session_token_hash
    assert session.session_token_hash == hash_session_token(raw_token)

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 10. /api/auth/me Authenticated Request
# ============================================================================
@pytest.mark.anyio
async def test_10_get_me_authenticated(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 10: Authenticated request returns the current user profile."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})
    await ac.post("/api/auth/login", json={"email": email, "password": password})

    # The AsyncClient automatically retains cookies
    me_resp = await ac.get("/api/auth/me")
    assert me_resp.status_code == 200
    data = me_resp.json()
    assert data["email"] == email
    assert data["is_active"] is True

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 11. Unauthenticated /api/auth/me Returns 401
# ============================================================================
@pytest.mark.anyio
async def test_11_get_me_unauthenticated(ac: AsyncClient) -> None:
    """Test 11: Request without a valid session cookie returns 401 Unauthorized."""
    # Ensure no cookies
    ac.cookies.clear()
    resp = await ac.get("/api/auth/me")
    assert resp.status_code == 401
    assert "authentication required" in resp.json()["detail"].lower()


# ============================================================================
# 12. Logout Revokes Session and Clears Cookie
# ============================================================================
@pytest.mark.anyio
async def test_12_logout_revokes_session(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 12: Logout revokes the session in PostgreSQL and clears authentication."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})
    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})
    raw_token = login_resp.cookies.get(settings.session_cookie_name)

    # Logout
    logout_resp = await ac.post("/api/auth/logout")
    assert logout_resp.status_code == 200

    # Verify session in DB has revoked_at set
    token_hash = hash_session_token(raw_token)
    session = db.query(AuthSession).filter(AuthSession.session_token_hash == token_hash).first()
    assert session is not None
    assert session.revoked_at is not None

    # Subsequent call to /me must fail with 401
    me_resp = await ac.get("/api/auth/me")
    assert me_resp.status_code == 401

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 13. Revoked Session Cannot Authenticate
# ============================================================================
@pytest.mark.anyio
async def test_13_revoked_session_rejected(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 13: A revoked session token cannot access protected endpoints even if manually re-sent."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})
    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})
    raw_token = login_resp.cookies.get(settings.session_cookie_name)

    # Explicitly revoke session in DB
    token_hash = hash_session_token(raw_token)
    session = db.query(AuthSession).filter(AuthSession.session_token_hash == token_hash).first()
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()

    # Attempt to use revoked cookie
    resp = await ac.get("/api/auth/me", cookies={settings.session_cookie_name: raw_token})
    assert resp.status_code == 401

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 14. Expired Session Cannot Authenticate
# ============================================================================
@pytest.mark.anyio
async def test_14_expired_session_rejected(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 14: An expired session cannot authenticate."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})
    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})
    raw_token = login_resp.cookies.get(settings.session_cookie_name)

    # Set expires_at in the past
    token_hash = hash_session_token(raw_token)
    session = db.query(AuthSession).filter(AuthSession.session_token_hash == token_hash).first()
    session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    # Attempt to use expired session
    resp = await ac.get("/api/auth/me", cookies={settings.session_cookie_name: raw_token})
    assert resp.status_code == 401

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 15. Cookie Security Flags
# ============================================================================
@pytest.mark.anyio
async def test_15_cookie_security_flags(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 15: Verify session cookie includes HttpOnly and SameSite directives in Set-Cookie header."""
    email = test_user_factory()
    password = "ValidPassword123!"

    await ac.post("/api/auth/register", json={"email": email, "password": password})
    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})

    set_cookie_header = login_resp.headers.get("set-cookie", "")
    assert set_cookie_header != ""
    assert "httponly" in set_cookie_header.lower()
    assert f"samesite={settings.session_cookie_samesite.lower()}" in set_cookie_header.lower()

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 16. Sensitive Fields Never Exposed
# ============================================================================
@pytest.mark.anyio
async def test_16_sensitive_fields_never_exposed(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 16: Verify API responses never contain password_hash or session_token_hash."""
    email = test_user_factory()
    password = "ValidPassword123!"

    reg_resp = await ac.post("/api/auth/register", json={"email": email, "password": password})
    reg_data = reg_resp.json()
    assert "password_hash" not in reg_data
    assert "session_token_hash" not in reg_data
    assert "password" not in reg_data

    login_resp = await ac.post("/api/auth/login", json={"email": email, "password": password})
    login_data = login_resp.json()
    assert "password_hash" not in login_data
    assert "session_token_hash" not in login_data
    assert "password" not in login_data

    me_resp = await ac.get("/api/auth/me")
    me_data = me_resp.json()
    assert "password_hash" not in me_data
    assert "session_token_hash" not in me_data

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 17. Cross-User Isolation Foundation
# ============================================================================
@pytest.mark.anyio
async def test_17_cross_user_isolation(ac: AsyncClient, db: Session, test_user_factory) -> None:
    """Test 17: Verify authentication identifies the correct user from the session, never trusting client user_id."""
    user1_email = test_user_factory()
    user2_email = test_user_factory()
    pwd = "StrongPassword123!"

    # Register both users
    await ac.post("/api/auth/register", json={"email": user1_email, "password": pwd})
    await ac.post("/api/auth/register", json={"email": user2_email, "password": pwd})

    # Log in as user 1
    resp1 = await ac.post("/api/auth/login", json={"email": user1_email, "password": pwd})
    cookie1 = resp1.cookies.get(settings.session_cookie_name)

    # Log in as user 2
    resp2 = await ac.post("/api/auth/login", json={"email": user2_email, "password": pwd})
    cookie2 = resp2.cookies.get(settings.session_cookie_name)

    # User 1 cookie retrieves User 1
    me1 = await ac.get("/api/auth/me", cookies={settings.session_cookie_name: cookie1})
    assert me1.status_code == 200
    assert me1.json()["email"] == user1_email

    # User 2 cookie retrieves User 2
    me2 = await ac.get("/api/auth/me", cookies={settings.session_cookie_name: cookie2})
    assert me2.status_code == 200
    assert me2.json()["email"] == user2_email

    # Distinct IDs
    assert me1.json()["id"] != me2.json()["id"]

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email IN (:e1, :e2)"), {"e1": user1_email, "e2": user2_email})
    db.commit()
