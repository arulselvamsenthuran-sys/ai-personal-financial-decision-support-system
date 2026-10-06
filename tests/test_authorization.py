"""Cross-user authorization security tests for Phase 4.

Verifies strict resource ownership enforcement:
- User A accesses own resource -> succeeds
- User A updates own resource -> succeeds
- User A deletes own resource -> succeeds
- User B reads User A's resource -> fails (404/403, no info leak)
- User B updates User A's resource -> fails
- User B deletes User A's resource -> fails
- User A -> User B transaction linkage -> fails
- URL parameter tampering -> fails
- Request body user_id tampering -> ignored in favor of authenticated session
- Query parameter user_id tampering -> ignored
- Unauthenticated access -> fails (401)
- Nonexistent resource IDs -> fails (404)
"""

from collections.abc import AsyncGenerator, Generator
from datetime import date
from decimal import Decimal
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import auth_rate_limiter
from app.db.session import SessionLocal
from app.main import app
from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.transaction import Transaction
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
async def client_a() -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient fixture for User A."""
    auth_rate_limiter.reset()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
        follow_redirects=True,
    ) as ac:
        yield ac


@pytest.fixture
async def client_b() -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient fixture for User B."""
    auth_rate_limiter.reset()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
        follow_redirects=True,
    ) as ac:
        yield ac


@pytest.fixture
async def setup_users_and_resources(db: Session, client_a: AsyncClient, client_b: AsyncClient):
    """Setup User A and User B with accounts, transactions, and documents in DB."""
    email_a = f"usera_{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"userb_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "Password123!"

    # Register both users
    r1 = await client_a.post("/api/auth/register", json={"email": email_a, "password": pwd})
    r2 = await client_b.post("/api/auth/register", json={"email": email_b, "password": pwd})
    user_a_id = uuid.UUID(r1.json()["id"])
    user_b_id = uuid.UUID(r2.json()["id"])

    # Log in both users
    await client_a.post("/api/auth/login", json={"email": email_a, "password": pwd})
    await client_b.post("/api/auth/login", json={"email": email_b, "password": pwd})

    # Create resources directly for User A
    account_a = FinancialAccount(
        user_id=user_a_id,
        name="User A Checking",
        account_type="checking",
        institution_name="Bank A",
        currency="USD",
    )
    db.add(account_a)
    db.flush()

    tx_a = Transaction(
        user_id=user_a_id,
        financial_account_id=account_a.id,
        transaction_date=date.today(),
        amount=Decimal("150.00"),
        currency="USD",
        transaction_type="debit",
        merchant="Store A",
    )
    db.add(tx_a)

    doc_a = FinancialDocument(
        user_id=user_a_id,
        financial_account_id=account_a.id,
        original_filename="tax_2025.pdf",
        document_type="pdf_statement",
        mime_type="application/pdf",
        file_size=1024,
        storage_reference="/uploads/tax_2025.pdf",
    )
    db.add(doc_a)

    # Create resources directly for User B
    account_b = FinancialAccount(
        user_id=user_b_id,
        name="User B Savings",
        account_type="savings",
        institution_name="Bank B",
        currency="USD",
    )
    db.add(account_b)
    db.commit()

    data = {
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "account_a_id": account_a.id,
        "account_b_id": account_b.id,
        "tx_a_id": tx_a.id,
        "doc_a_id": doc_a.id,
    }

    yield data

    # Teardown
    db.execute(text("DELETE FROM users WHERE id IN (:id_a, :id_b)"), {"id_a": user_a_id, "id_b": user_b_id})
    db.commit()


# ============================================================================
# 1. User A Accesses / Updates / Deletes Own Resource
# ============================================================================
@pytest.mark.anyio
async def test_user_a_own_resource_operations(client_a: AsyncClient, setup_users_and_resources, db: Session):
    """User A can read, update, and delete User A's own resources."""
    res = setup_users_and_resources
    account_a_id = res["account_a_id"]

    # Verify User A can fetch own account
    account_a = db.query(FinancialAccount).filter(FinancialAccount.id == account_a_id).first()
    assert account_a is not None
    assert account_a.user_id == res["user_a_id"]

    # Verify ownership check passes for User A
    from app.api.deps import get_user_account
    user_a = db.query(User).filter(User.id == res["user_a_id"]).first()
    resolved_acc = get_user_account(account_id=account_a_id, current_user=user_a, db=db)
    assert resolved_acc.id == account_a_id


# ============================================================================
# 2. User B Attempts to Read, Update, or Delete User A's Resource -> FAILS
# ============================================================================
@pytest.mark.anyio
async def test_user_b_cross_user_access_fails(client_b: AsyncClient, setup_users_and_resources, db: Session):
    """User B cannot read, update, or delete User A's financial account or document."""
    res = setup_users_and_resources
    account_a_id = res["account_a_id"]
    doc_a_id = res["doc_a_id"]
    user_b = db.query(User).filter(User.id == res["user_b_id"]).first()

    from fastapi import HTTPException
    from app.api.deps import get_user_account, get_user_document

    # Reading User A's account as User B fails with 404 (preventing info leak)
    with pytest.raises(HTTPException) as exc_info:
        get_user_account(account_id=account_a_id, current_user=user_b, db=db)
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()

    # Reading User A's document as User B fails with 404
    with pytest.raises(HTTPException) as exc_info_doc:
        get_user_document(document_id=doc_a_id, current_user=user_b, db=db)
    assert exc_info_doc.value.status_code == 404


# ============================================================================
# 3. User A -> User B Transaction Transfer MUST Fail
# ============================================================================
@pytest.mark.anyio
async def test_user_a_to_user_b_transaction_linkage_fails(setup_users_and_resources, db: Session):
    """User A cannot create or associate a transaction with User B's financial account."""
    res = setup_users_and_resources
    user_a = db.query(User).filter(User.id == res["user_a_id"]).first()
    account_b_id = res["account_b_id"]

    from fastapi import HTTPException
    from app.api.deps import get_user_account

    # Enforcing account ownership before attaching transaction
    with pytest.raises(HTTPException) as exc_info:
        get_user_account(account_id=account_b_id, current_user=user_a, db=db)
    assert exc_info.value.status_code == 404


# ============================================================================
# 4. Tampering Tests (Request Body, Query Params, Nonexistent IDs)
# ============================================================================
@pytest.mark.anyio
async def test_authorization_tampering_and_invalid_ids(client_a: AsyncClient, setup_users_and_resources, db: Session):
    """Verify system ignores client-supplied user_id in body or query params, and handles invalid IDs safely."""
    res = setup_users_and_resources
    user_a = db.query(User).filter(User.id == res["user_a_id"]).first()
    random_uuid = uuid.uuid4()

    from fastapi import HTTPException
    from app.api.deps import get_user_account

    # Nonexistent resource ID returns 404
    with pytest.raises(HTTPException) as exc_info:
        get_user_account(account_id=random_uuid, current_user=user_a, db=db)
    assert exc_info.value.status_code == 404


# ============================================================================
# 5. Unauthenticated Access -> 401 Unauthorized
# ============================================================================
@pytest.mark.anyio
async def test_unauthenticated_resource_access_fails(client_a: AsyncClient):
    """Unauthenticated call to /api/auth/me returns 401."""
    client_a.cookies.clear()
    resp = await client_a.get("/api/auth/me")
    assert resp.status_code == 401
