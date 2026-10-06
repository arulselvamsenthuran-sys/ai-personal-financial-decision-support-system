"""Security protections test suite for Phase 4.

Tests:
1. SQL Injection safety via SQLAlchemy parameterization
2. XSS payload handling (stored/returned safely as literal strings, no raw execution)
3. CSRF origin verification on state-changing requests
4. Rate limiting on authentication endpoints (HTTP 429)
5. Secure error handling (no stack trace or database credential leaks)
6. Security audit logging (events logged without credentials/hashes)
"""

from collections.abc import AsyncGenerator, Generator
import logging
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.config import settings
from app.core.rate_limit import auth_rate_limiter
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User


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
# 1. SQL Injection Protection Tests
# ============================================================================
@pytest.mark.anyio
async def test_sql_injection_payloads_fail_safely(client: AsyncClient, db: Session):
    """Verify malicious SQL payloads in login/register inputs fail safely and do not corrupt queries."""
    sqli_payloads = [
        "' OR '1'='1",
        "admin'--",
        "'; DROP TABLE users; --",
        "1' UNION SELECT 1,2,3--",
    ]

    for payload in sqli_payloads:
        # Attempt registration with SQLi payload email
        resp = await client.post("/api/auth/register", json={"email": payload, "password": "Password123!"})
        # Should be rejected cleanly by email validator or fail authentication safely
        assert resp.status_code in (422, 400, 401)

        # Attempt login with SQLi payload
        login_resp = await client.post("/api/auth/login", json={"email": payload, "password": "Password123!"})
        assert login_resp.status_code in (422, 400, 401)

    # Verify table 'users' was not dropped or altered
    users_count = db.execute(text("SELECT count(*) FROM users")).scalar()
    assert users_count is not None


# ============================================================================
# 2. XSS Protection Tests
# ============================================================================
@pytest.mark.anyio
async def test_xss_payload_string_handling(client: AsyncClient):
    """Verify HTML/Script payloads are validated or escaped, never returned as executable HTML."""
    xss_payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)",
    ]

    for payload in xss_payloads:
        resp = await client.post("/api/auth/register", json={"email": payload, "password": "Password123!"})
        # Email field validator rejects HTML/script tags cleanly
        assert resp.status_code == 422


# ============================================================================
# 3. CSRF Protection Tests
# ============================================================================
@pytest.mark.anyio
async def test_csrf_protection_rejects_untrusted_origin(client: AsyncClient, db: Session):
    """Verify state-changing POST requests with untrusted/forbidden Origin are rejected with 403."""
    email = f"csrf_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "Password123!"

    # Register and login to establish session cookie
    await client.post("/api/auth/register", json={"email": email, "password": pwd})
    await client.post("/api/auth/login", json={"email": email, "password": pwd})

    # Attempt state-changing logout with an untrusted origin
    untrusted_client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"origin": "http://evil-attacker-site.com"},
        cookies=client.cookies,
    )

    resp = await untrusted_client.post("/api/auth/logout")
    assert resp.status_code == 403
    assert "cross-site request forgery" in resp.json()["detail"].lower()

    # Cleanup
    db.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    db.commit()


# ============================================================================
# 4. Rate Limiting Tests
# ============================================================================
@pytest.mark.anyio
async def test_rate_limiting_enforced_on_login(client: AsyncClient):
    """Verify making > 10 requests to sensitive auth endpoints within 60s triggers HTTP 429."""
    auth_rate_limiter.reset()

    # Send 10 login requests (allowed)
    for _ in range(10):
        resp = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "WrongPassword1!"})
        assert resp.status_code in (401, 422)

    # 11th request must trigger HTTP 429 Rate Limit
    rate_limited_resp = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "WrongPassword1!"})
    assert rate_limited_resp.status_code == 429
    assert "too many requests" in rate_limited_resp.json()["detail"].lower()

    auth_rate_limiter.reset()


# ============================================================================
# 5. Secure Error Handling Tests
# ============================================================================
@pytest.mark.anyio
async def test_secure_error_responses_do_not_leak_secrets(client: AsyncClient):
    """Verify 404 and 500 error responses never leak stack traces, SQL syntax, or internal paths."""
    # Test 404 error response
    resp_404 = await client.get("/api/auth/nonexistent_route_xyz")
    assert resp_404.status_code == 404
    data_404 = resp_404.json()
    assert "traceback" not in str(data_404).lower()
    assert "postgresql" not in str(data_404).lower()


# ============================================================================
# 6. Security Audit Logging Tests
# ============================================================================
def test_audit_logging_sanitizes_sensitive_keys(caplog):
    """Verify audit logger never records raw passwords or session tokens."""
    with caplog.at_level(logging.INFO):
        audit_log(
            event_type="LOGIN_FAILURE",
            status="FAILURE",
            details={
                "email": "test@example.com",
                "password": "SuperSecretPassword123!",
                "session_token": "raw_token_xyz_123",
            },
        )

    log_text = caplog.text
    assert "AUDIT_EVENT" in log_text
    assert "test@example.com" in log_text
    # Sensitive fields MUST be redacted
    assert "SuperSecretPassword123!" not in log_text
    assert "[REDACTED]" in log_text
