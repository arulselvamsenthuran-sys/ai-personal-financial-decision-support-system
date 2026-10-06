"""API integration and security authorization tests for Phase 6 Financial Data Model."""

from datetime import date
from decimal import Decimal
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rate_limit import auth_rate_limiter
from app.db.session import SessionLocal
from app.main import app
from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.transaction import Transaction
from app.models.user import User


@pytest.fixture
def db() -> Session:
    """Yield database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
async def setup_two_users_with_financial_data(db: Session):
    """Setup User A and User B with financial accounts, transactions, and documents."""
    auth_rate_limiter.reset()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", headers={"origin": "http://localhost:5173"}) as client_a:
        async with AsyncClient(transport=transport, base_url="http://test", headers={"origin": "http://localhost:5173"}) as client_b:
            email_a = f"usera_fin_{uuid.uuid4().hex[:8]}@example.com"
            email_b = f"userb_fin_{uuid.uuid4().hex[:8]}@example.com"
            password = "Password123!"

            # Register
            r_a = await client_a.post("/api/auth/register", json={"email": email_a, "password": password})
            r_b = await client_b.post("/api/auth/register", json={"email": email_b, "password": password})
            user_a_id = uuid.UUID(r_a.json()["id"])
            user_b_id = uuid.UUID(r_b.json()["id"])

            # Login to populate session cookies
            await client_a.post("/api/auth/login", json={"email": email_a, "password": password})
            await client_b.post("/api/auth/login", json={"email": email_b, "password": password})

            # Create data for User A in DB
            acc_a = FinancialAccount(
                user_id=user_a_id,
                name="User A Checking",
                account_type="bank",
                institution_name="Bank Alpha",
                account_identifier_masked="****1111",
                currency="USD",
                opening_balance=Decimal("1000.0000"),
            )
            db.add(acc_a)
            db.flush()

            tx_a = Transaction(
                user_id=user_a_id,
                financial_account_id=acc_a.id,
                transaction_date=date(2026, 9, 15),
                amount=Decimal("50.2500"),
                currency="USD",
                transaction_type="debit",
                merchant="Coffee Shop",
                description="Morning Coffee",
                category="Food",
                status="posted",
                source="manual",
            )
            db.add(tx_a)

            doc_a = FinancialDocument(
                user_id=user_a_id,
                financial_account_id=acc_a.id,
                original_filename="bank_statement_aug.pdf",
                document_type="bank_statement",
                mime_type="application/pdf",
                file_size=204800,
                file_hash="a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890",
                storage_reference="/secure_storage/user_a/bank_statement_aug.pdf",
                processing_status="processed",
            )
            db.add(doc_a)

            # Create data for User B in DB
            acc_b = FinancialAccount(
                user_id=user_b_id,
                name="User B Savings",
                account_type="savings",
                institution_name="Bank Beta",
                account_identifier_masked="****2222",
                currency="USD",
                opening_balance=Decimal("5000.0000"),
            )
            db.add(acc_b)
            db.flush()

            tx_b = Transaction(
                user_id=user_b_id,
                financial_account_id=acc_b.id,
                transaction_date=date(2026, 9, 16),
                amount=Decimal("200.0000"),
                currency="USD",
                transaction_type="credit",
                merchant="Payroll",
                description="Salary deposit",
                category="Income",
                status="posted",
                source="bank_import",
            )
            db.add(tx_b)

            doc_b = FinancialDocument(
                user_id=user_b_id,
                financial_account_id=acc_b.id,
                original_filename="tax_return.pdf",
                document_type="pdf_statement",
                mime_type="application/pdf",
                file_size=102400,
                storage_reference="/secure_storage/user_b/tax_return.pdf",
                processing_status="uploaded",
            )
            db.add(doc_b)
            db.commit()

            yield {
                "client_a": client_a,
                "client_b": client_b,
                "user_a_id": user_a_id,
                "user_b_id": user_b_id,
                "acc_a_id": acc_a.id,
                "acc_b_id": acc_b.id,
                "tx_a_id": tx_a.id,
                "tx_b_id": tx_b.id,
                "doc_a_id": doc_a.id,
                "doc_b_id": doc_b.id,
            }

            # Cleanup
            db.execute(text("DELETE FROM users WHERE id IN (:id_a, :id_b)"), {"id_a": user_a_id, "id_b": user_b_id})
            db.commit()


@pytest.mark.anyio
async def test_get_financial_accounts_isolation(setup_two_users_with_financial_data):
    """Verify GET /api/financial/accounts returns only current user's accounts."""
    env = setup_two_users_with_financial_data
    client_a: AsyncClient = env["client_a"]
    client_b: AsyncClient = env["client_b"]

    resp_a = await client_a.get("/api/financial/accounts")
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert len(data_a) == 1
    assert data_a[0]["id"] == str(env["acc_a_id"])
    assert data_a[0]["name"] == "User A Checking"
    assert data_a[0]["account_identifier_masked"] == "****1111"
    assert data_a[0]["opening_balance"] == "1000.0000"

    resp_b = await client_b.get("/api/financial/accounts")
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert len(data_b) == 1
    assert data_b[0]["id"] == str(env["acc_b_id"])
    assert data_b[0]["name"] == "User B Savings"


@pytest.mark.anyio
async def test_get_transactions_isolation_and_filter(setup_two_users_with_financial_data):
    """Verify GET /api/financial/transactions enforces ownership and parameter filtering."""
    env = setup_two_users_with_financial_data
    client_a: AsyncClient = env["client_a"]
    client_b: AsyncClient = env["client_b"]

    # User A listing transactions
    resp_a = await client_a.get("/api/financial/transactions")
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert len(data_a) == 1
    assert data_a[0]["id"] == str(env["tx_a_id"])
    assert data_a[0]["merchant"] == "Coffee Shop"
    assert data_a[0]["amount"] == "50.2500"
    assert data_a[0]["currency"] == "USD"

    # User A passing own account_id filter
    resp_a_filtered = await client_a.get(f"/api/financial/transactions?account_id={env['acc_a_id']}")
    assert resp_a_filtered.status_code == 200
    assert len(resp_a_filtered.json()) == 1

    # User A attempting to filter transactions by User B's account_id -> FAILS 404
    resp_a_tamper = await client_a.get(f"/api/financial/transactions?account_id={env['acc_b_id']}")
    assert resp_a_tamper.status_code == 404


@pytest.mark.anyio
async def test_get_financial_documents_isolation(setup_two_users_with_financial_data):
    """Verify GET /api/financial/documents returns only current user's documents."""
    env = setup_two_users_with_financial_data
    client_a: AsyncClient = env["client_a"]
    client_b: AsyncClient = env["client_b"]

    resp_a = await client_a.get("/api/financial/documents")
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert len(data_a) == 1
    assert data_a[0]["id"] == str(env["doc_a_id"])
    assert data_a[0]["original_filename"] == "bank_statement_aug.pdf"
    assert data_a[0]["file_hash"] == "a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890"

    resp_b = await client_b.get("/api/financial/documents")
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert len(data_b) == 1
    assert data_b[0]["id"] == str(env["doc_b_id"])
    assert data_b[0]["original_filename"] == "tax_return.pdf"


@pytest.mark.anyio
async def test_unauthenticated_financial_endpoints_fail():
    """Unauthenticated requests to financial endpoints must return 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"origin": "http://localhost:5173"}) as client:
        r1 = await client.get("/api/financial/accounts")
        assert r1.status_code == 401

        r2 = await client.get("/api/financial/transactions")
        assert r2.status_code == 401

        r3 = await client.get("/api/financial/documents")
        assert r3.status_code == 401
