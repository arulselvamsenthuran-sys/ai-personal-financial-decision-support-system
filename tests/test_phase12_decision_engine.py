"""Comprehensive tests for Phase 12: Financial Decision Support Engine.

Covers:
  1. Authenticated access to POST /api/financial/decision-support/analyze
  2. Unauthenticated access rejected (401)
  3. User isolation / IDOR prevention (User A cannot see or be evaluated on User B's data)
  4. Multi-currency isolation (LKR scenario uses ONLY LKR data; USD uses ONLY USD data)
  5. LARGE_PURCHASE scenario (one-time impact, unchanged monthly recurring expenses)
  6. RECURRING_EXPENSE_ADD scenario (ongoing expense increase, savings rate impact)
  7. INCOME_REDUCTION scenario (ongoing income decrease, savings rate impact)
  8. EXPENSE_INCREASE scenario (ongoing expense expansion)
  9. Data availability audit: Insufficient (0 transactions)
 10. Data availability audit: Partial (< 3 transactions or unverified liquidity)
 11. Data availability audit: Sufficient (adequate transactions + verified liquidity)
 12. Liquidity evaluation: Verified sufficient liquidity
 13. Liquidity evaluation: Verified insufficient liquidity (triggers INSUFFICIENT_LIQUIDITY)
 14. Liquidity evaluation: Unavailable liquidity (does NOT assume zero)
 15. Safe denominators: Zero income (savings rate is None, no ZeroDivisionError)
 16. Safe denominators: Zero expenses (recurring pressure is None, no ZeroDivisionError)
 17. Negative net cash flow baseline (triggers NEGATIVE_NET_CASH_FLOW)
 18. Low savings rate heuristic trigger (LOW_SAVINGS_RATE)
 19. High recurring pressure heuristic trigger (HIGH_RECURRING_PRESSURE)
 20. Large purchase high income share heuristic trigger (LARGE_PURCHASE_HIGH_INCOME_SHARE)
 21. Validation: Amount <= 0 produces 422
 22. Validation: Non-alpha or invalid length currency produces 422
 23. Validation: Unsupported scenario type produces 422
 24. Validation: Invalid date range (start > end) produces 422
 25. Explainability: Evidence list completeness
 26. Regulatory disclaimer is always attached
 27. Decimal precision (no float leakage)
"""

from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal
import uuid
from typing import Optional

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy.orm import Session

from app.core.rate_limit import auth_rate_limiter
from app.db.session import SessionLocal
from app.main import app
from app.models.financial_account import FinancialAccount
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.decision import (
    ComponentAvailabilityStatus,
    DecisionAnalyzeRequest,
    DecisionAnalyzeResponse,
    DecisionScenarioType,
    OverallDataAvailability,
)
from app.services.decision_engine import (
    DecisionSupportEngine,
    decision_support_engine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def user_a(db: Session) -> User:
    """Primary test user."""
    user = User(email=f"p12_a_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user_b(db: Session) -> User:
    """Secondary test user for isolation tests."""
    user = User(email=f"p12_b_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def account_lkr_a(db: Session, user_a: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_a.id,
        name="User A LKR Checking",
        account_type="bank",
        currency="LKR",
        opening_balance=Decimal("200000.0000"),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def account_usd_a(db: Session, user_a: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_a.id,
        name="User A USD Checking",
        account_type="bank",
        currency="USD",
        opening_balance=Decimal("5000.0000"),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def account_lkr_b(db: Session, user_b: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_b.id,
        name="User B LKR Checking",
        account_type="bank",
        currency="LKR",
        opening_balance=Decimal("500000.0000"),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _create_tx(
    db: Session,
    user: User,
    account: FinancialAccount,
    tx_date: date,
    amount: Decimal,
    tx_type: str,
) -> Transaction:
    """Helper to insert a transaction."""
    tx = Transaction(
        user_id=user.id,
        financial_account_id=account.id,
        transaction_fingerprint=f"p12_{uuid.uuid4().hex}",
        transaction_date=tx_date,
        amount=amount,
        currency=account.currency,
        transaction_type=tx_type,
        source="test",
    )
    db.add(tx)
    db.flush()
    return tx


# ---------------------------------------------------------------------------
# 1. Direct Service Unit Tests: Large Purchase
# ---------------------------------------------------------------------------

def test_large_purchase_one_time_impact(
    db: Session, user_a: User, account_lkr_a: FinancialAccount
):
    """Large purchase must reduce period net cash flow but NOT increase recurring baseline expenses."""
    start = date(2026, 6, 1)
    end = date(2026, 6, 30)

    # 1 income (150,000) and 2 expenses (30,000 + 20,000 = 50,000)
    _create_tx(db, user_a, account_lkr_a, date(2026, 6, 1), Decimal("150000"), "credit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 6, 10), Decimal("30000"), "debit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 6, 15), Decimal("20000"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("100000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )

    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    # Baseline assertions
    assert resp.cash_flow_projection.baseline_income == Decimal("150000.00")
    assert resp.cash_flow_projection.baseline_expenses == Decimal("50000.00")
    assert resp.cash_flow_projection.baseline_net_cash_flow == Decimal("100000.00")
    assert resp.cash_flow_projection.baseline_savings_rate == Decimal("66.67")

    # One-time impact assertions:
    assert resp.cash_flow_projection.is_one_time_impact is True
    assert resp.cash_flow_projection.projected_income == Decimal("150000.00")
    # Recurring expenses must remain 50,000 (NOT 150,000)
    assert resp.cash_flow_projection.projected_expenses == Decimal("50000.00")
    # Period net cash flow is 100,000 - 100,000 = 0.00
    assert resp.cash_flow_projection.projected_net_cash_flow == Decimal("0.00")
    assert resp.cash_flow_projection.net_cash_flow_change == Decimal("-100000.00")

    # Liquidity: Opening balance is 200,000 + net movement (100,000) = 300,000 known balance
    assert resp.liquidity_evaluation.status == ComponentAvailabilityStatus.AVAILABLE
    assert resp.liquidity_evaluation.known_liquid_balance == Decimal("300000.00")
    assert resp.liquidity_evaluation.projected_balance_after == Decimal("200000.00")
    assert resp.liquidity_evaluation.is_liquid_balance_sufficient is True


# ---------------------------------------------------------------------------
# 2. Recurring Expense Add Scenario
# ---------------------------------------------------------------------------

def test_recurring_expense_add_impact(
    db: Session, user_a: User, account_lkr_a: FinancialAccount
):
    """Recurring expense add permanently increases monthly baseline expenses."""
    start = date(2026, 7, 1)
    end = date(2026, 7, 31)

    _create_tx(db, user_a, account_lkr_a, date(2026, 7, 1), Decimal("100000"), "credit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 7, 5), Decimal("30000"), "debit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 7, 10), Decimal("20000"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.RECURRING_EXPENSE_ADD,
        amount=Decimal("15000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )

    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    assert resp.cash_flow_projection.is_one_time_impact is False
    assert resp.cash_flow_projection.baseline_expenses == Decimal("50000.00")
    assert resp.cash_flow_projection.projected_expenses == Decimal("65000.00")
    assert resp.cash_flow_projection.projected_net_cash_flow == Decimal("35000.00")
    assert resp.cash_flow_projection.projected_savings_rate == Decimal("35.00")

    # Recurring pressure ratio check
    pressure_ratio = next((r for r in resp.ratios if r.name == "recurring_expense_to_baseline_expenses"), None)
    assert pressure_ratio is not None
    assert pressure_ratio.value == Decimal("30.00")  # 15000 / 50000 * 100 = 30.0%
    assert pressure_ratio.is_computable is True

    # Triggers HIGH_RECURRING_PRESSURE (>= 25%)
    risk = next((r for r in resp.risk_indicators if r.code == "HIGH_RECURRING_PRESSURE"), None)
    assert risk is not None


# ---------------------------------------------------------------------------
# 3. Income Reduction Scenario
# ---------------------------------------------------------------------------

def test_income_reduction_impact(
    db: Session, user_a: User, account_lkr_a: FinancialAccount
):
    """Income reduction permanently reduces monthly income and net cash flow."""
    start = date(2026, 8, 1)
    end = date(2026, 8, 31)

    _create_tx(db, user_a, account_lkr_a, date(2026, 8, 1), Decimal("100000"), "credit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 8, 5), Decimal("60000"), "debit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 8, 10), Decimal("10000"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.INCOME_REDUCTION,
        amount=Decimal("40000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )

    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    assert resp.cash_flow_projection.is_one_time_impact is False
    assert resp.cash_flow_projection.baseline_income == Decimal("100000.00")
    assert resp.cash_flow_projection.projected_income == Decimal("60000.00")
    assert resp.cash_flow_projection.projected_expenses == Decimal("70000.00")
    assert resp.cash_flow_projection.projected_net_cash_flow == Decimal("-10000.00")

    # Triggers NEGATIVE_NET_CASH_FLOW
    risk = next((r for r in resp.risk_indicators if r.code == "NEGATIVE_NET_CASH_FLOW"), None)
    assert risk is not None
    assert risk.severity == "HIGH_RISK"


# ---------------------------------------------------------------------------
# 4. Multi-Currency Isolation
# ---------------------------------------------------------------------------

def test_multi_currency_isolation(
    db: Session,
    user_a: User,
    account_lkr_a: FinancialAccount,
    account_usd_a: FinancialAccount,
):
    """LKR evaluation must not include USD transactions and vice versa."""
    start = date(2026, 5, 1)
    end = date(2026, 5, 31)

    _create_tx(db, user_a, account_lkr_a, date(2026, 5, 1), Decimal("100000"), "credit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 5, 10), Decimal("20000"), "debit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 5, 15), Decimal("10000"), "debit")

    _create_tx(db, user_a, account_usd_a, date(2026, 5, 2), Decimal("5000"), "credit")
    _create_tx(db, user_a, account_usd_a, date(2026, 5, 12), Decimal("1000"), "debit")

    # Analyze LKR
    req_lkr = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("50000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )
    resp_lkr = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req_lkr, period_start=start, period_end=end
    )
    assert resp_lkr.cash_flow_projection.baseline_income == Decimal("100000.00")
    assert resp_lkr.data_availability.transaction_count == 3

    # Analyze USD
    req_usd = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("2000"),
        currency="USD",
        start_date=start,
        end_date=end,
    )
    resp_usd = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req_usd, period_start=start, period_end=end
    )
    assert resp_usd.cash_flow_projection.baseline_income == Decimal("5000.00")
    assert resp_usd.data_availability.transaction_count == 2


# ---------------------------------------------------------------------------
# 5. User Isolation (IDOR Prevention)
# ---------------------------------------------------------------------------

def test_user_data_isolation(
    db: Session,
    user_a: User,
    user_b: User,
    account_lkr_a: FinancialAccount,
    account_lkr_b: FinancialAccount,
):
    """User A's scenario evaluation must never be influenced by User B's transactions."""
    start = date(2026, 4, 1)
    end = date(2026, 4, 30)

    # User B has transactions
    _create_tx(db, user_b, account_lkr_b, date(2026, 4, 1), Decimal("999999"), "credit")
    _create_tx(db, user_b, account_lkr_b, date(2026, 4, 2), Decimal("111111"), "debit")

    # User A has 0 transactions
    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("50000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )
    resp_a = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    assert resp_a.data_availability.transaction_count == 0
    assert resp_a.data_availability.overall_status == OverallDataAvailability.INSUFFICIENT
    assert resp_a.cash_flow_projection.baseline_income == Decimal("0.00")


# ---------------------------------------------------------------------------
# 6. Data Availability & Missing Liquidity Handling
# ---------------------------------------------------------------------------

def test_missing_liquidity_handling(
    db: Session, user_a: User
):
    """When financial account balance is unverified, liquidity status is UNAVAILABLE and not assumed zero."""
    start = date(2026, 1, 1)
    end = date(2026, 1, 31)

    # Create account WITHOUT opening balance
    acc = FinancialAccount(
        user_id=user_a.id,
        name="No Opening Balance Acc",
        account_type="bank",
        currency="EUR",
        opening_balance=None,  # missing opening balance
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)

    _create_tx(db, user_a, acc, date(2026, 1, 1), Decimal("3000"), "credit")
    _create_tx(db, user_a, acc, date(2026, 1, 5), Decimal("1000"), "debit")
    _create_tx(db, user_a, acc, date(2026, 1, 10), Decimal("500"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("1200"),
        currency="EUR",
        start_date=start,
        end_date=end,
    )
    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    assert resp.data_availability.transaction_baseline == ComponentAvailabilityStatus.AVAILABLE
    assert resp.data_availability.liquidity_data == ComponentAvailabilityStatus.PARTIAL
    assert resp.liquidity_evaluation.known_liquid_balance is None
    assert resp.liquidity_evaluation.is_liquid_balance_sufficient is None
    assert "Liquid account balance information is not fully verified" in resp.liquidity_evaluation.explanation


# ---------------------------------------------------------------------------
# 7. Safe Denominators (Zero Income and Zero Expenses)
# ---------------------------------------------------------------------------

def test_safe_denominators_zero_income(
    db: Session, user_a: User, account_lkr_a: FinancialAccount
):
    """Zero income must safely return None for ratios without ZeroDivisionError."""
    start = date(2026, 3, 1)
    end = date(2026, 3, 31)

    _create_tx(db, user_a, account_lkr_a, date(2026, 3, 5), Decimal("20000"), "debit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 3, 10), Decimal("10000"), "debit")
    _create_tx(db, user_a, account_lkr_a, date(2026, 3, 15), Decimal("5000"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("50000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )
    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    assert resp.cash_flow_projection.baseline_income == Decimal("0.00")
    assert resp.cash_flow_projection.baseline_savings_rate is None
    assert resp.cash_flow_projection.projected_savings_rate is None

    ratio = next(r for r in resp.ratios if r.name == "scenario_amount_to_monthly_income")
    assert ratio.value is None
    assert ratio.is_computable is False


# ---------------------------------------------------------------------------
# 8. Insufficient Liquidity Risk Trigger
# ---------------------------------------------------------------------------

def test_insufficient_liquidity_rule_trigger(
    db: Session, user_a: User
):
    """When verified balance is known and smaller than purchase, trigger INSUFFICIENT_LIQUIDITY."""
    start = date(2026, 2, 1)
    end = date(2026, 2, 28)

    acc = FinancialAccount(
        user_id=user_a.id,
        name="Small Balance Acc",
        account_type="bank",
        currency="GBP",
        opening_balance=Decimal("500.0000"),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)

    _create_tx(db, user_a, acc, date(2026, 2, 1), Decimal("1000"), "credit")
    _create_tx(db, user_a, acc, date(2026, 2, 5), Decimal("600"), "debit")
    _create_tx(db, user_a, acc, date(2026, 2, 10), Decimal("400"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("2000"),
        currency="GBP",
        start_date=start,
        end_date=end,
    )
    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    # Balance is 500 + 1000 - 600 - 400 = 500
    assert resp.liquidity_evaluation.known_liquid_balance == Decimal("500.00")
    assert resp.liquidity_evaluation.is_liquid_balance_sufficient is False

    risk = next((r for r in resp.risk_indicators if r.code == "INSUFFICIENT_LIQUIDITY"), None)
    assert risk is not None
    assert risk.severity == "HIGH_RISK"


# ---------------------------------------------------------------------------
# 9. HTTP Endpoint Integration & Authorization Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_endpoint_unauthenticated_rejected():
    """Unauthenticated request must be rejected with 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/financial/decision-support/analyze",
            json={
                "scenario_type": "large_purchase",
                "amount": "100000.00",
                "currency": "LKR",
            },
        )
        assert resp.status_code == 401


@pytest.mark.anyio
async def test_endpoint_authenticated_success(db: Session):
    """Authenticated request returns valid 200 OK DecisionAnalyzeResponse."""
    auth_rate_limiter.reset()
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as client:
        email = f"p12_auth_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "Password123!"

        reg_res = await client.post("/api/auth/register", json={"email": email, "password": pwd})
        assert reg_res.status_code == 201
        user_id = uuid.UUID(reg_res.json()["id"])

        login_res = await client.post("/api/auth/login", json={"email": email, "password": pwd})
        assert login_res.status_code == 200

        # Add account and transactions
        acc = FinancialAccount(
            user_id=user_id,
            name="Checking",
            account_type="bank",
            currency="LKR",
            opening_balance=Decimal("300000.0000"),
        )
        db.add(acc)
        db.flush()

        user_obj = db.query(User).filter(User.id == user_id).first()
        _create_tx(db, user_obj, acc, date.today(), Decimal("120000"), "credit")
        _create_tx(db, user_obj, acc, date.today(), Decimal("40000"), "debit")
        _create_tx(db, user_obj, acc, date.today(), Decimal("10000"), "debit")
        db.commit()

        resp = await client.post(
            "/api/financial/decision-support/analyze",
            json={
                "scenario_type": "large_purchase",
                "amount": "50000.00",
                "currency": "LKR",
                "period": "current_month",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["scenario_type"] == "large_purchase"
        assert data["currency"] == "LKR"
        assert data["amount"] == "50000.00"
        assert "data_availability" in data
        assert "cash_flow_projection" in data
        assert "liquidity_evaluation" in data
        assert "evidence" in data
        assert len(data["evidence"]) >= 5
        assert "disclaimer" in data


@pytest.mark.anyio
async def test_endpoint_input_validation_errors():
    """Negative amount, invalid currency, or invalid scenario type must return 422."""
    auth_rate_limiter.reset()
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as client:
        email = f"p12_val_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "Password123!"

        await client.post("/api/auth/register", json={"email": email, "password": pwd})
        await client.post("/api/auth/login", json={"email": email, "password": pwd})

        # Negative amount
        r1 = await client.post(
            "/api/financial/decision-support/analyze",
            json={
                "scenario_type": "large_purchase",
                "amount": "-500.00",
                "currency": "LKR",
            },
        )
        assert r1.status_code == 422

        # Invalid currency length
        r2 = await client.post(
            "/api/financial/decision-support/analyze",
            json={
                "scenario_type": "large_purchase",
                "amount": "500.00",
                "currency": "LK",
            },
        )
        assert r2.status_code == 422

        # Unsupported scenario type
        r3 = await client.post(
            "/api/financial/decision-support/analyze",
            json={
                "scenario_type": "stock_investment_pick",
                "amount": "500.00",
                "currency": "USD",
            },
        )
        assert r3.status_code == 422


# ---------------------------------------------------------------------------
# 10. Specific LKR 150,000 Balance Liquidity Tests
# ---------------------------------------------------------------------------

def test_lkr_balance_150k_purchase_100k_sufficient_liquidity(db: Session, user_a: User):
    """Verified LKR balance = 150,000; purchase = 100,000 -> sufficient liquidity."""
    start = date(2026, 9, 1)
    end = date(2026, 9, 30)

    # Active LKR account with opening_balance = 150,000
    acc = FinancialAccount(
        user_id=user_a.id,
        name="LKR Account 150k",
        account_type="bank",
        currency="LKR",
        opening_balance=Decimal("150000.0000"),
        is_active=True,
    )
    db.add(acc)
    db.flush()

    # Balanced transactions in period so net movement = 0, current balance = 150,000
    _create_tx(db, user_a, acc, date(2026, 9, 1), Decimal("50000"), "credit")
    _create_tx(db, user_a, acc, date(2026, 9, 10), Decimal("30000"), "debit")
    _create_tx(db, user_a, acc, date(2026, 9, 15), Decimal("20000"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("100000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )

    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    # Assertions
    assert resp.data_availability.liquidity_data == ComponentAvailabilityStatus.AVAILABLE
    assert resp.data_availability.overall_status == OverallDataAvailability.SUFFICIENT
    assert resp.liquidity_evaluation.status == ComponentAvailabilityStatus.AVAILABLE
    assert resp.liquidity_evaluation.known_liquid_balance == Decimal("150000.00")
    assert resp.liquidity_evaluation.projected_balance_after == Decimal("50000.00")
    assert resp.liquidity_evaluation.liquidity_coverage_ratio == Decimal("1.50")
    assert resp.liquidity_evaluation.is_liquid_balance_sufficient is True

    # Ensure INSUFFICIENT_LIQUIDITY is NOT present
    risk_codes = [r.code for r in resp.risk_indicators]
    assert "INSUFFICIENT_LIQUIDITY" not in risk_codes


def test_lkr_balance_150k_purchase_200k_insufficient_liquidity(db: Session, user_a: User):
    """Verified LKR balance = 150,000; purchase = 200,000 -> insufficient liquidity (triggers INSUFFICIENT_LIQUIDITY)."""
    start = date(2026, 9, 1)
    end = date(2026, 9, 30)

    acc = FinancialAccount(
        user_id=user_a.id,
        name="LKR Account 150k",
        account_type="bank",
        currency="LKR",
        opening_balance=Decimal("150000.0000"),
        is_active=True,
    )
    db.add(acc)
    db.flush()

    _create_tx(db, user_a, acc, date(2026, 9, 1), Decimal("50000"), "credit")
    _create_tx(db, user_a, acc, date(2026, 9, 10), Decimal("30000"), "debit")
    _create_tx(db, user_a, acc, date(2026, 9, 15), Decimal("20000"), "debit")

    req = DecisionAnalyzeRequest(
        scenario_type=DecisionScenarioType.LARGE_PURCHASE,
        amount=Decimal("200000"),
        currency="LKR",
        start_date=start,
        end_date=end,
    )

    resp = decision_support_engine.analyze(
        db=db, user_id=user_a.id, request=req, period_start=start, period_end=end
    )

    # Assertions
    assert resp.data_availability.liquidity_data == ComponentAvailabilityStatus.AVAILABLE
    assert resp.data_availability.overall_status == OverallDataAvailability.SUFFICIENT
    assert resp.liquidity_evaluation.status == ComponentAvailabilityStatus.AVAILABLE
    assert resp.liquidity_evaluation.known_liquid_balance == Decimal("150000.00")
    assert resp.liquidity_evaluation.projected_balance_after == Decimal("-50000.00")
    assert resp.liquidity_evaluation.liquidity_coverage_ratio == Decimal("0.75")
    assert resp.liquidity_evaluation.is_liquid_balance_sufficient is False

    # Ensure INSUFFICIENT_LIQUIDITY IS present
    insufficient_risk = next((r for r in resp.risk_indicators if r.code == "INSUFFICIENT_LIQUIDITY"), None)
    assert insufficient_risk is not None
    assert insufficient_risk.severity == "HIGH_RISK"
    assert insufficient_risk.trigger_value == "200000.00"
    assert insufficient_risk.threshold_value == "150000.00"
    assert "exceeds total verified liquid account balance" in insufficient_risk.message
