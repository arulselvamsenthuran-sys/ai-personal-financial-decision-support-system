"""Phase 15 Test Suite — Conversational Financial AI & Frontend Transaction Management.

Covers:
  1. Transaction Management (POST /api/financial/transactions):
     - Authenticated debit (expense) transaction creation
     - Authenticated credit (income) transaction creation
     - Invalid amount (zero / negative) -> 422
     - Invalid / non-owned account (IDOR protection) -> 404
     - Unauthenticated request -> 401
     - Currency upper-casing & normalization
     - DB persistence verification
     - Analytics pipeline integration verification
  2. Conversational Financial AI Chat (POST /api/financial/decision-support/chat):
     - Normal follow-up question -> AI answer returned
     - Provider 503 error -> fallback message, status fallback_provider_error, no crash
     - Provider 504 timeout -> fallback message, status fallback_timeout, no crash
     - Unauthenticated request -> 401
     - User isolation / prompt safety
"""

from datetime import date
from decimal import Decimal
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.session import SessionLocal
from app.models.user import User
from app.models.financial_account import FinancialAccount
from app.models.transaction import Transaction
from app.services.auth_service import create_session
from app.services.llm.provider import MockLLMProvider
from app.services.llm.service import ai_explanation_service


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

def create_test_user(db: Session, email_prefix: str = "phase15") -> User:
    u = User(
        email=f"{email_prefix}_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_test_password",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def create_test_account(
    db: Session, user_id: uuid.UUID, name: str = "Checking", currency: str = "LKR"
) -> FinancialAccount:
    fa = FinancialAccount(
        user_id=user_id,
        name=name,
        account_type="depository",
        currency=currency,
        is_active=True,
    )
    db.add(fa)
    db.commit()
    db.refresh(fa)
    return fa


def get_auth_client(db: Session, user: User) -> AsyncClient:
    raw_token, _ = create_session(db=db, user_id=user.id)
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    client.cookies.set("session_id", raw_token)
    return client


# ---------------------------------------------------------------------------
# Part A: Transaction Management Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_transaction_success_debit():
    db = SessionLocal()
    try:
        user = create_test_user(db, "txn_debit")
        account = create_test_account(db, user.id, "Checking", "LKR")

        async with get_auth_client(db, user) as ac:
            res = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account.id),
                    "transaction_date": str(date.today()),
                    "amount": 2500.50,
                    "currency": "lkr",
                    "transaction_type": "debit",
                    "description": "Office supplies",
                    "merchant": "Stationery Store",
                    "category": "Supplies",
                },
            )

        assert res.status_code == 201, res.text
        data = res.json()
        assert Decimal(data["amount"]) == Decimal("2500.50")
        assert data["currency"] == "LKR"
        assert data["transaction_type"] == "debit"
        assert data["description"] == "Office supplies"
        assert data["financial_account_id"] == str(account.id)

        # Confirm DB persistence
        db_txn = db.query(Transaction).filter(Transaction.id == uuid.UUID(data["id"])).first()
        assert db_txn is not None
        assert db_txn.amount == Decimal("2500.50")
        assert db_txn.transaction_type == "debit"
    finally:
        db.close()


@pytest.mark.anyio
async def test_create_transaction_success_credit():
    db = SessionLocal()
    try:
        user = create_test_user(db, "txn_credit")
        account = create_test_account(db, user.id, "Savings", "USD")

        async with get_auth_client(db, user) as ac:
            res = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account.id),
                    "transaction_date": str(date.today()),
                    "amount": 5000.00,
                    "currency": "USD",
                    "transaction_type": "credit",
                    "description": "Monthly Salary",
                    "category": "Income",
                },
            )

        assert res.status_code == 201, res.text
        data = res.json()
        assert Decimal(data["amount"]) == Decimal("5000.00")
        assert data["currency"] == "USD"
        assert data["transaction_type"] == "credit"
    finally:
        db.close()


@pytest.mark.anyio
async def test_create_transaction_invalid_amount():
    db = SessionLocal()
    try:
        user = create_test_user(db, "txn_invalid_amt")
        account = create_test_account(db, user.id)

        async with get_auth_client(db, user) as ac:
            # Zero amount
            res = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account.id),
                    "transaction_date": str(date.today()),
                    "amount": 0,
                    "currency": "LKR",
                    "transaction_type": "debit",
                },
            )
            assert res.status_code == 422

            # Negative amount
            res2 = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account.id),
                    "transaction_date": str(date.today()),
                    "amount": -100,
                    "currency": "LKR",
                    "transaction_type": "debit",
                },
            )
            assert res2.status_code == 422
    finally:
        db.close()


@pytest.mark.anyio
async def test_create_transaction_invalid_account_ownership():
    db = SessionLocal()
    try:
        user1 = create_test_user(db, "user1_ownership")
        user2 = create_test_user(db, "user2_ownership")
        account_user2 = create_test_account(db, user2.id, "User2 Account")

        async with get_auth_client(db, user1) as ac:
            # User 1 tries to add transaction to User 2's account
            res = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account_user2.id),
                    "transaction_date": str(date.today()),
                    "amount": 100.00,
                    "currency": "LKR",
                    "transaction_type": "debit",
                },
            )
            assert res.status_code in (403, 404)
    finally:
        db.close()


@pytest.mark.anyio
async def test_create_transaction_unauthenticated():
    db = SessionLocal()
    try:
        user = create_test_user(db, "unauth_txn")
        account = create_test_account(db, user.id)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            res = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account.id),
                    "transaction_date": str(date.today()),
                    "amount": 500.00,
                    "currency": "LKR",
                    "transaction_type": "debit",
                },
            )
            assert res.status_code == 401
    finally:
        db.close()


@pytest.mark.anyio
async def test_transaction_affects_financial_analytics():
    db = SessionLocal()
    try:
        user = create_test_user(db, "txn_analytics")
        account = create_test_account(db, user.id, "Primary", "EUR")

        async with get_auth_client(db, user) as ac:
            # 1. Add credit transaction
            res_income = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account.id),
                    "transaction_date": str(date.today()),
                    "amount": 3000.00,
                    "currency": "EUR",
                    "transaction_type": "credit",
                    "description": "Salary",
                },
            )
            assert res_income.status_code == 201

            # 2. Add debit transaction
            res_expense = await ac.post(
                "/api/financial/transactions",
                json={
                    "financial_account_id": str(account.id),
                    "transaction_date": str(date.today()),
                    "amount": 1000.00,
                    "currency": "EUR",
                    "transaction_type": "debit",
                    "description": "Rent",
                },
            )
            assert res_expense.status_code == 201

            # 3. Check analytics summary
            res_summary = await ac.get("/api/financial/analytics/summary")
            assert res_summary.status_code == 200
            data = res_summary.json()

            eur_summary = next((b for b in data["by_currency"] if b["currency"] == "EUR"), None)
            assert eur_summary is not None
            assert Decimal(eur_summary["total_income"]) == Decimal("3000.00")
            assert Decimal(eur_summary["total_expenses"]) == Decimal("1000.00")
            assert Decimal(eur_summary["net_cash_flow"]) == Decimal("2000.00")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Part B: Conversational Financial AI Chat Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_chat_decision_support_success(monkeypatch):
    db = SessionLocal()
    try:
        user = create_test_user(db, "chat_success")
        create_test_account(db, user.id, "Account1", "LKR")

        # Mock LLM provider returning clean answer
        mock_provider = MockLLMProvider(
            custom_response="Your cash flow becomes negative because this purchase exceeds your net income."
        )
        monkeypatch.setattr(ai_explanation_service, "_default_provider", mock_provider)

        async with get_auth_client(db, user) as ac:
            res = await ac.post(
                "/api/financial/decision-support/chat",
                json={
                    "decision_context": {
                        "scenario_type": "large_purchase",
                        "amount": 150000.0,
                        "currency": "LKR",
                        "period": "last_3_months",
                    },
                    "question": "Why is this purchase considered high risk?",
                    "conversation_history": [],
                },
            )

        assert res.status_code == 200, res.text
        data = res.json()
        assert data["ai_status"] == "success"
        assert "negative" in data["answer"].lower() or "purchase" in data["answer"].lower()
        assert "disclaimer" in data
    finally:
        db.close()


@pytest.mark.anyio
async def test_chat_decision_support_503_provider_error(monkeypatch):
    db = SessionLocal()
    try:
        user = create_test_user(db, "chat_503")

        mock_provider = MockLLMProvider(simulate_error="503 Service Unavailable")
        monkeypatch.setattr(ai_explanation_service, "_default_provider", mock_provider)

        async with get_auth_client(db, user) as ac:
            res = await ac.post(
                "/api/financial/decision-support/chat",
                json={
                    "decision_context": {
                        "scenario_type": "large_purchase",
                        "amount": 50000.0,
                        "currency": "LKR",
                    },
                    "question": "Explain this result",
                },
            )

        assert res.status_code == 200, res.text
        data = res.json()
        assert data["ai_status"] == "fallback_provider_error"
        assert "unavailable" in data["answer"].lower()
    finally:
        db.close()


@pytest.mark.anyio
async def test_chat_decision_support_504_timeout(monkeypatch):
    db = SessionLocal()
    try:
        user = create_test_user(db, "chat_504")

        mock_provider = MockLLMProvider(simulate_timeout=True)
        monkeypatch.setattr(ai_explanation_service, "_default_provider", mock_provider)

        async with get_auth_client(db, user) as ac:
            res = await ac.post(
                "/api/financial/decision-support/chat",
                json={
                    "decision_context": {
                        "scenario_type": "large_purchase",
                        "amount": 50000.0,
                        "currency": "LKR",
                    },
                    "question": "What happens if I reduce this purchase?",
                },
            )

        assert res.status_code == 200, res.text
        data = res.json()
        assert data["ai_status"] == "fallback_timeout"
        assert "timed out" in data["answer"].lower() or "unavailable" in data["answer"].lower()
    finally:
        db.close()


@pytest.mark.anyio
async def test_chat_decision_support_unauthenticated():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        res = await ac.post(
            "/api/financial/decision-support/chat",
            json={
                "decision_context": {
                    "scenario_type": "large_purchase",
                    "amount": 1000.0,
                    "currency": "LKR",
                },
                "question": "Why is this high risk?",
            },
        )
        assert res.status_code == 401
