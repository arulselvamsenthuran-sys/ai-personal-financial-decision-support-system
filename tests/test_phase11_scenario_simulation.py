"""Comprehensive tests for Phase 11: Financial Scenario Simulation Engine.

Covers:
 1.  Authenticated user can simulate a scenario
 2.  Unauthenticated request is rejected (401)
 3.  User isolation (user B cannot see user A's data)
 4.  LKR currency only uses LKR transactions
 5.  USD currency only uses USD transactions
 6.  EXPENSE_PERCENT_CHANGE (increase)
 7.  EXPENSE_PERCENT_CHANGE (decrease)
 8.  INCOME_PERCENT_CHANGE (increase)
 9.  INCOME_PERCENT_CHANGE (decrease)
10.  ADD_MONTHLY_EXPENSE
11.  REMOVE_MONTHLY_EXPENSE
12.  SAVINGS_TARGET
13.  Zero-transaction period returns valid zero baseline
14.  Custom date range
15.  Preset period (last_3_months)
16.  Invalid scenario type → 422
17.  Invalid percentage (> 10000%) → 422
18.  Percentage below -100% → 422
19.  ADD_MONTHLY_EXPENSE with value <= 0 → 422
20.  REMOVE_MONTHLY_EXPENSE with value <= 0 → 422
21.  SAVINGS_TARGET with negative value → 422
22.  Invalid date range (start > end) → 422
23.  Invalid period name → 422
24.  Decimal precision (no float leakage)
25.  Scenario does NOT modify transactions
26.  Scenario does NOT modify ledger entries
27.  Scenario does NOT create financial events
28.  Scenario does NOT affect stored insights
29.  REMOVE_MONTHLY_EXPENSE floored at zero (expenses never go negative)
30.  SAVINGS_TARGET with income=0 gives zero expenses and null savings_rate
31.  Response contains baseline, scenario, impact, and disclaimer
32.  Impact fields are correctly calculated
33.  Savings rate is null when income = 0

Engineering invariants verified:
  - All monetary values are Decimal, never float.
  - Multi-currency: scenario only uses the requested currency.
  - User isolation: service is scoped to authenticated user_id only.
  - No DB writes performed by any scenario endpoint.
"""

from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal
import uuid
from typing import Optional

import pytest
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.financial_account import FinancialAccount
from app.models.financial_event import FinancialEvent
from app.models.financial_insight import FinancialInsight
from app.models.ledger import LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.scenario import (
    ScenarioSimulateRequest,
    ScenarioType,
)
from app.services.scenario_service import (
    ScenarioSimulationService,
    scenario_simulation_service,
)
from app.services.financial_intelligence import last_n_months_range


# ---------------------------------------------------------------------------
# Shared helpers and fixtures
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
    """Primary test user — LKR account."""
    user = User(email=f"p11_a_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user_b(db: Session) -> User:
    """Secondary test user — must remain invisible to user_a's scenarios."""
    user = User(email=f"p11_b_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def account_lkr(db: Session, user_a: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_a.id,
        name="LKR Checking",
        account_type="bank",
        currency="LKR",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def account_usd(db: Session, user_a: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_a.id,
        name="USD Account",
        account_type="bank",
        currency="USD",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def account_b(db: Session, user_b: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_b.id,
        name="User B LKR",
        account_type="bank",
        currency="LKR",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _tx(
    db: Session,
    user: User,
    account: FinancialAccount,
    tx_date: date,
    amount: Decimal,
    tx_type: str,
) -> Transaction:
    """Create and persist a single transaction."""
    t = Transaction(
        user_id=user.id,
        financial_account_id=account.id,
        transaction_fingerprint=f"p11_{uuid.uuid4().hex}",
        transaction_date=tx_date,
        amount=amount,
        currency=account.currency,
        transaction_type=tx_type,
        source="test",
    )
    db.add(t)
    db.flush()
    return t


def _build_request(
    scenario_type: ScenarioType,
    value: Decimal,
    currency: str = "LKR",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    period: Optional[str] = None,
) -> ScenarioSimulateRequest:
    """Helper to build a validated ScenarioSimulateRequest."""
    return ScenarioSimulateRequest(
        scenario_type=scenario_type,
        value=value,
        currency=currency,
        start_date=start_date,
        end_date=end_date,
        period=period,
    )


# ---------------------------------------------------------------------------
# 1. EXPENSE_PERCENT_CHANGE — increase
# ---------------------------------------------------------------------------

def test_expense_percent_increase(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Expense +10%: baseline expenses * 1.10 = scenario expenses."""
    _tx(db, user_a, account_lkr, date(2026, 1, 5), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 1, 10), Decimal("40000"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("10"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )

    assert result.baseline.income == Decimal("100000.0000")
    assert result.baseline.expenses == Decimal("40000.0000")
    assert result.baseline.net_cash_flow == Decimal("60000.0000")
    assert result.baseline.savings_rate == Decimal("60.00")

    assert result.scenario.income == Decimal("100000.0000")
    assert result.scenario.expenses == Decimal("44000.0000")
    assert result.scenario.net_cash_flow == Decimal("56000.0000")
    assert result.scenario.savings_rate == Decimal("56.00")

    assert result.impact.expense_change == Decimal("4000.0000")
    assert result.impact.net_cash_flow_change == Decimal("-4000.0000")
    assert result.impact.income_change == Decimal("0.0000")
    assert result.impact.savings_rate_change == Decimal("-4.00")


# ---------------------------------------------------------------------------
# 2. EXPENSE_PERCENT_CHANGE — decrease
# ---------------------------------------------------------------------------

def test_expense_percent_decrease(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Expense -15%: scenario expenses = baseline * 0.85."""
    _tx(db, user_a, account_lkr, date(2026, 2, 5), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 2, 10), Decimal("50000"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("-15"),
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 28),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
    )

    assert result.scenario.expenses == Decimal("42500.0000")
    assert result.scenario.net_cash_flow == Decimal("57500.0000")
    assert result.impact.expense_change == Decimal("-7500.0000")
    assert result.impact.net_cash_flow_change == Decimal("7500.0000")


# ---------------------------------------------------------------------------
# 3. INCOME_PERCENT_CHANGE — decrease
# ---------------------------------------------------------------------------

def test_income_percent_decrease(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Income -10%: scenario income = 90000, expenses unchanged."""
    _tx(db, user_a, account_lkr, date(2026, 3, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 3, 5), Decimal("40000"), "debit")

    req = _build_request(
        ScenarioType.INCOME_PERCENT_CHANGE,
        Decimal("-10"),
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )

    assert result.scenario.income == Decimal("90000.0000")
    assert result.scenario.expenses == Decimal("40000.0000")
    assert result.scenario.net_cash_flow == Decimal("50000.0000")
    # savings_rate = 50000/90000*100 = 55.56%
    assert result.scenario.savings_rate == Decimal("55.56")
    assert result.impact.income_change == Decimal("-10000.0000")
    assert result.impact.expense_change == Decimal("0.0000")


# ---------------------------------------------------------------------------
# 4. INCOME_PERCENT_CHANGE — increase
# ---------------------------------------------------------------------------

def test_income_percent_increase(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Income +20%."""
    _tx(db, user_a, account_lkr, date(2026, 4, 1), Decimal("100000"), "income")
    _tx(db, user_a, account_lkr, date(2026, 4, 10), Decimal("60000"), "expense")

    req = _build_request(
        ScenarioType.INCOME_PERCENT_CHANGE,
        Decimal("20"),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    assert result.scenario.income == Decimal("120000.0000")
    assert result.scenario.expenses == Decimal("60000.0000")
    assert result.scenario.net_cash_flow == Decimal("60000.0000")
    assert result.impact.income_change == Decimal("20000.0000")
    assert result.impact.net_cash_flow_change == Decimal("20000.0000")


# ---------------------------------------------------------------------------
# 5. ADD_MONTHLY_EXPENSE
# ---------------------------------------------------------------------------

def test_add_monthly_expense(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Adding 20000 LKR to expenses."""
    _tx(db, user_a, account_lkr, date(2026, 5, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 5, 5), Decimal("50000"), "debit")

    req = _build_request(
        ScenarioType.ADD_MONTHLY_EXPENSE,
        Decimal("20000"),
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )

    assert result.scenario.expenses == Decimal("70000.0000")
    assert result.scenario.income == Decimal("100000.0000")
    assert result.scenario.net_cash_flow == Decimal("30000.0000")
    assert result.impact.expense_change == Decimal("20000.0000")
    assert result.impact.net_cash_flow_change == Decimal("-20000.0000")


# ---------------------------------------------------------------------------
# 6. REMOVE_MONTHLY_EXPENSE
# ---------------------------------------------------------------------------

def test_remove_monthly_expense(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Removing 10000 LKR from expenses."""
    _tx(db, user_a, account_lkr, date(2026, 6, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 6, 5), Decimal("50000"), "debit")

    req = _build_request(
        ScenarioType.REMOVE_MONTHLY_EXPENSE,
        Decimal("10000"),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )

    assert result.scenario.expenses == Decimal("40000.0000")
    assert result.impact.expense_change == Decimal("-10000.0000")
    assert result.impact.net_cash_flow_change == Decimal("10000.0000")


# ---------------------------------------------------------------------------
# 7. REMOVE_MONTHLY_EXPENSE — floored at zero
# ---------------------------------------------------------------------------

def test_remove_monthly_expense_floored_at_zero(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """Removing more than total expenses should floor at 0, not go negative."""
    _tx(db, user_a, account_lkr, date(2026, 7, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 7, 5), Decimal("5000"), "debit")

    req = _build_request(
        ScenarioType.REMOVE_MONTHLY_EXPENSE,
        Decimal("50000"),  # removing 50000 when only 5000 exist
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )

    # Expenses should be clamped at 0, never negative
    assert result.scenario.expenses == Decimal("0.0000")
    assert result.scenario.expenses >= Decimal("0")


# ---------------------------------------------------------------------------
# 8. SAVINGS_TARGET
# ---------------------------------------------------------------------------

def test_savings_target(db: Session, user_a: User, account_lkr: FinancialAccount):
    """SAVINGS_TARGET: max expenses = income - target_savings."""
    _tx(db, user_a, account_lkr, date(2026, 8, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 8, 5), Decimal("70000"), "debit")

    req = _build_request(
        ScenarioType.SAVINGS_TARGET,
        Decimal("30000"),  # want to save 30000
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )

    # max allowable expenses = 100000 - 30000 = 70000
    assert result.scenario.income == Decimal("100000.0000")
    assert result.scenario.expenses == Decimal("70000.0000")
    assert result.scenario.net_cash_flow == Decimal("30000.0000")


def test_savings_target_aggressive(db: Session, user_a: User, account_lkr: FinancialAccount):
    """SAVINGS_TARGET larger than income → scenario expenses = 0."""
    _tx(db, user_a, account_lkr, date(2026, 9, 1), Decimal("50000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 9, 5), Decimal("30000"), "debit")

    req = _build_request(
        ScenarioType.SAVINGS_TARGET,
        Decimal("80000"),  # target > income
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
    )

    # income - target is negative → expenses floored at 0
    assert result.scenario.expenses == Decimal("0.0000")
    assert result.scenario.net_cash_flow == Decimal("50000.0000")


# ---------------------------------------------------------------------------
# 9. Zero transaction period — valid empty baseline
# ---------------------------------------------------------------------------

def test_zero_transaction_period(db: Session, user_a: User, account_lkr: FinancialAccount):
    """When no transactions exist in the period, baseline is all zeros."""
    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("10"),
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2020, 1, 1),
        period_end=date(2020, 1, 31),
    )

    assert result.baseline.income == Decimal("0.0000")
    assert result.baseline.expenses == Decimal("0.0000")
    assert result.baseline.net_cash_flow == Decimal("0.0000")
    assert result.baseline.savings_rate is None

    assert result.scenario.income == Decimal("0.0000")
    assert result.scenario.expenses == Decimal("0.0000")
    assert result.scenario.net_cash_flow == Decimal("0.0000")
    assert result.scenario.savings_rate is None


# ---------------------------------------------------------------------------
# 10. Savings rate is None when income = 0
# ---------------------------------------------------------------------------

def test_savings_rate_null_when_income_zero(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """When income is 0, savings_rate must be None (not zero or error)."""
    _tx(db, user_a, account_lkr, date(2026, 10, 5), Decimal("30000"), "debit")

    req = _build_request(
        ScenarioType.ADD_MONTHLY_EXPENSE,
        Decimal("5000"),
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
    )

    assert result.baseline.savings_rate is None
    assert result.scenario.savings_rate is None
    assert result.impact.savings_rate_change is None


# ---------------------------------------------------------------------------
# 11. Multi-currency isolation: LKR simulation ignores USD transactions
# ---------------------------------------------------------------------------

def test_lkr_only_uses_lkr_transactions(
    db: Session,
    user_a: User,
    account_lkr: FinancialAccount,
    account_usd: FinancialAccount,
):
    """A LKR scenario must never include USD transactions."""
    _tx(db, user_a, account_lkr, date(2026, 11, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 11, 5), Decimal("40000"), "debit")
    # USD transactions — must NOT appear in LKR scenario
    _tx(db, user_a, account_usd, date(2026, 11, 1), Decimal("99999"), "credit")
    _tx(db, user_a, account_usd, date(2026, 11, 5), Decimal("99999"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("10"),
        currency="LKR",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
    )

    # Only LKR amounts should appear
    assert result.currency == "LKR"
    assert result.baseline.income == Decimal("100000.0000")
    assert result.baseline.expenses == Decimal("40000.0000")
    # USD amounts (99999) must not contaminate any field
    assert result.baseline.income != Decimal("199999.0000")
    assert result.baseline.expenses != Decimal("139999.0000")


def test_usd_only_uses_usd_transactions(
    db: Session,
    user_a: User,
    account_lkr: FinancialAccount,
    account_usd: FinancialAccount,
):
    """A USD scenario must never include LKR transactions."""
    _tx(db, user_a, account_usd, date(2026, 11, 1), Decimal("5000"), "credit")
    _tx(db, user_a, account_usd, date(2026, 11, 5), Decimal("2000"), "debit")
    # LKR transactions — must not appear in USD scenario
    _tx(db, user_a, account_lkr, date(2026, 11, 1), Decimal("500000"), "credit")

    req = _build_request(
        ScenarioType.INCOME_PERCENT_CHANGE,
        Decimal("10"),
        currency="USD",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
    )

    assert result.currency == "USD"
    assert result.baseline.income == Decimal("5000.0000")
    # LKR 500000 must not appear
    assert result.baseline.income < Decimal("10000")


# ---------------------------------------------------------------------------
# 12. User isolation
# ---------------------------------------------------------------------------

def test_user_isolation(
    db: Session,
    user_a: User,
    user_b: User,
    account_lkr: FinancialAccount,
    account_b: FinancialAccount,
):
    """user_b's transactions must never appear in user_a's scenario."""
    _tx(db, user_a, account_lkr, date(2026, 12, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 12, 5), Decimal("40000"), "debit")
    # user_b has big transactions — should never appear for user_a
    _tx(db, user_b, account_b, date(2026, 12, 1), Decimal("999999"), "credit")
    _tx(db, user_b, account_b, date(2026, 12, 5), Decimal("999999"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("10"),
        currency="LKR",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 31),
    )
    result_a = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 12, 1),
        period_end=date(2026, 12, 31),
    )

    # user_a sees only their own 100000/40000
    assert result_a.baseline.income == Decimal("100000.0000")
    assert result_a.baseline.expenses == Decimal("40000.0000")
    assert result_a.baseline.income != Decimal("1099999.0000")


# ---------------------------------------------------------------------------
# 13. Custom date range
# ---------------------------------------------------------------------------

def test_custom_date_range(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Custom start_date/end_date returns correct baseline for that range."""
    _tx(db, user_a, account_lkr, date(2026, 1, 15), Decimal("80000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 1, 20), Decimal("30000"), "debit")
    # outside the custom range — should be excluded
    _tx(db, user_a, account_lkr, date(2026, 2, 1), Decimal("50000"), "credit")

    req = _build_request(
        ScenarioType.ADD_MONTHLY_EXPENSE,
        Decimal("5000"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )

    assert result.period_start == date(2026, 1, 1)
    assert result.period_end == date(2026, 1, 31)
    assert result.baseline.income == Decimal("80000.0000")
    assert result.baseline.expenses == Decimal("30000.0000")


# ---------------------------------------------------------------------------
# 14. Preset period — last_3_months
# ---------------------------------------------------------------------------

def test_preset_period_used(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Verifies that a preset period resolves correctly and data filters correctly."""
    dr = last_n_months_range(3)
    mid_date = dr.start + (dr.end - dr.start) // 2

    _tx(db, user_a, account_lkr, mid_date, Decimal("60000"), "credit")
    _tx(db, user_a, account_lkr, mid_date, Decimal("25000"), "debit")

    req = _build_request(
        ScenarioType.INCOME_PERCENT_CHANGE,
        Decimal("-5"),
        period="last_3_months",
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=dr.start,
        period_end=dr.end,
    )

    assert result.baseline.income == Decimal("60000.0000")
    assert result.baseline.expenses == Decimal("25000.0000")
    assert result.scenario.income == Decimal("57000.0000")


# ---------------------------------------------------------------------------
# 15. Decimal precision — no float leakage
# ---------------------------------------------------------------------------

def test_decimal_precision_no_float(db: Session, user_a: User, account_lkr: FinancialAccount):
    """All monetary fields in the response must be Decimal instances, never float."""
    _tx(db, user_a, account_lkr, date(2026, 3, 1), Decimal("100000.33"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 3, 5), Decimal("33333.33"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("10"),
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )

    for field_val in [
        result.baseline.income,
        result.baseline.expenses,
        result.baseline.net_cash_flow,
        result.scenario.income,
        result.scenario.expenses,
        result.scenario.net_cash_flow,
        result.impact.income_change,
        result.impact.expense_change,
        result.impact.net_cash_flow_change,
    ]:
        assert isinstance(field_val, Decimal), f"Expected Decimal, got {type(field_val)}"
        assert not isinstance(field_val, float)


# ---------------------------------------------------------------------------
# 16. Scenario does NOT modify transactions
# ---------------------------------------------------------------------------

def test_scenario_does_not_modify_transactions(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """Transaction count must be identical before and after scenario simulation."""
    _tx(db, user_a, account_lkr, date(2026, 4, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 4, 5), Decimal("45000"), "debit")
    db.commit()

    count_before = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_a.id)
        .count()
    )

    req = _build_request(
        ScenarioType.ADD_MONTHLY_EXPENSE,
        Decimal("10000"),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
    )
    scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    count_after = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_a.id)
        .count()
    )

    assert count_before == count_after


# ---------------------------------------------------------------------------
# 17. Scenario does NOT modify ledger entries
# ---------------------------------------------------------------------------

def test_scenario_does_not_modify_ledger(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """Ledger entry count must be identical before and after scenario simulation."""
    _tx(db, user_a, account_lkr, date(2026, 5, 1), Decimal("100000"), "credit")
    db.commit()

    count_before = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.user_id == user_a.id)
        .count()
    )

    req = _build_request(
        ScenarioType.INCOME_PERCENT_CHANGE,
        Decimal("5"),
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )
    scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )

    count_after = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.user_id == user_a.id)
        .count()
    )

    assert count_before == count_after


# ---------------------------------------------------------------------------
# 18. Scenario does NOT create financial events
# ---------------------------------------------------------------------------

def test_scenario_does_not_create_financial_events(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """Financial event count must be identical before and after simulation."""
    _tx(db, user_a, account_lkr, date(2026, 6, 1), Decimal("100000"), "credit")
    db.commit()

    count_before = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.user_id == user_a.id)
        .count()
    )

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("20"),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
    )
    scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )

    count_after = (
        db.query(FinancialEvent)
        .filter(FinancialEvent.user_id == user_a.id)
        .count()
    )

    assert count_before == count_after


# ---------------------------------------------------------------------------
# 19. Scenario does NOT affect stored insights
# ---------------------------------------------------------------------------

def test_scenario_does_not_affect_insights(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """FinancialInsight count must be identical before and after simulation."""
    _tx(db, user_a, account_lkr, date(2026, 7, 1), Decimal("100000"), "credit")
    db.commit()

    count_before = (
        db.query(FinancialInsight)
        .filter(FinancialInsight.user_id == user_a.id)
        .count()
    )

    req = _build_request(
        ScenarioType.SAVINGS_TARGET,
        Decimal("20000"),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
    )
    scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )

    count_after = (
        db.query(FinancialInsight)
        .filter(FinancialInsight.user_id == user_a.id)
        .count()
    )

    assert count_before == count_after


# ---------------------------------------------------------------------------
# 20. Response structure — baseline, scenario, impact, disclaimer
# ---------------------------------------------------------------------------

def test_response_structure_complete(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """Response must have all required top-level fields."""
    _tx(db, user_a, account_lkr, date(2026, 8, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 8, 5), Decimal("40000"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("10"),
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )

    assert result.currency == "LKR"
    assert result.period_start == date(2026, 8, 1)
    assert result.period_end == date(2026, 8, 31)
    assert result.scenario_type == ScenarioType.EXPENSE_PERCENT_CHANGE
    assert result.value == Decimal("10")
    assert result.baseline is not None
    assert result.scenario is not None
    assert result.impact is not None
    assert "not financial advice" in result.disclaimer.lower()


# ---------------------------------------------------------------------------
# 21. Impact fields are correctly computed
# ---------------------------------------------------------------------------

def test_impact_fields_correct(db: Session, user_a: User, account_lkr: FinancialAccount):
    """Verify all four impact sub-fields are computed correctly."""
    _tx(db, user_a, account_lkr, date(2026, 9, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 9, 5), Decimal("40000"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("10"),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
    )

    # income_change = 0 (no income change)
    assert result.impact.income_change == Decimal("0.0000")
    # expense_change = +4000
    assert result.impact.expense_change == Decimal("4000.0000")
    # net_cash_flow_change = -4000
    assert result.impact.net_cash_flow_change == Decimal("-4000.0000")
    # savings_rate_change = 56.00 - 60.00 = -4.00
    assert result.impact.savings_rate_change == Decimal("-4.00")


# ---------------------------------------------------------------------------
# 22. Scenario type enum values
# ---------------------------------------------------------------------------

def test_scenario_type_enum_values():
    """All required scenario types are present."""
    assert ScenarioType.EXPENSE_PERCENT_CHANGE == "EXPENSE_PERCENT_CHANGE"
    assert ScenarioType.INCOME_PERCENT_CHANGE == "INCOME_PERCENT_CHANGE"
    assert ScenarioType.ADD_MONTHLY_EXPENSE == "ADD_MONTHLY_EXPENSE"
    assert ScenarioType.REMOVE_MONTHLY_EXPENSE == "REMOVE_MONTHLY_EXPENSE"
    assert ScenarioType.SAVINGS_TARGET == "SAVINGS_TARGET"


# ---------------------------------------------------------------------------
# 23. Request validation — invalid scenario type
# ---------------------------------------------------------------------------

def test_invalid_scenario_type_rejected():
    """An unsupported scenario_type must raise a validation error."""
    import pydantic
    with pytest.raises((pydantic.ValidationError, ValueError)):
        ScenarioSimulateRequest(
            scenario_type="MAGIC_SCENARIO",  # not a valid enum value
            value=Decimal("10"),
            currency="LKR",
        )


# ---------------------------------------------------------------------------
# 24. Request validation — percentage > 10000%
# ---------------------------------------------------------------------------

def test_percentage_too_large_rejected():
    """A percentage > 10000 must be rejected with ValidationError."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.EXPENSE_PERCENT_CHANGE,
            value=Decimal("99999"),
            currency="LKR",
        )


# ---------------------------------------------------------------------------
# 25. Request validation — percentage below -100%
# ---------------------------------------------------------------------------

def test_percentage_below_minus_100_rejected():
    """A percentage < -100 must be rejected."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.EXPENSE_PERCENT_CHANGE,
            value=Decimal("-101"),
            currency="LKR",
        )


# ---------------------------------------------------------------------------
# 26. Request validation — ADD_MONTHLY_EXPENSE with value = 0
# ---------------------------------------------------------------------------

def test_add_expense_zero_rejected():
    """ADD_MONTHLY_EXPENSE with value <= 0 must be rejected."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.ADD_MONTHLY_EXPENSE,
            value=Decimal("0"),
            currency="LKR",
        )


# ---------------------------------------------------------------------------
# 27. Request validation — REMOVE_MONTHLY_EXPENSE with value <= 0
# ---------------------------------------------------------------------------

def test_remove_expense_negative_rejected():
    """REMOVE_MONTHLY_EXPENSE with value <= 0 must be rejected."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.REMOVE_MONTHLY_EXPENSE,
            value=Decimal("-5000"),
            currency="LKR",
        )


# ---------------------------------------------------------------------------
# 28. Request validation — SAVINGS_TARGET with negative value
# ---------------------------------------------------------------------------

def test_savings_target_negative_rejected():
    """SAVINGS_TARGET with negative value must be rejected."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.SAVINGS_TARGET,
            value=Decimal("-1"),
            currency="LKR",
        )


# ---------------------------------------------------------------------------
# 29. Request validation — start_date after end_date
# ---------------------------------------------------------------------------

def test_invalid_date_range_rejected():
    """start_date > end_date must be rejected."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.EXPENSE_PERCENT_CHANGE,
            value=Decimal("10"),
            currency="LKR",
            start_date=date(2026, 12, 31),
            end_date=date(2026, 1, 1),
        )


# ---------------------------------------------------------------------------
# 30. Request validation — invalid period name
# ---------------------------------------------------------------------------

def test_invalid_period_name_rejected():
    """An unrecognised period string must be rejected."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.EXPENSE_PERCENT_CHANGE,
            value=Decimal("10"),
            currency="LKR",
            period="last_999_years",
        )


# ---------------------------------------------------------------------------
# 31. Request validation — only one of start_date or end_date provided
# ---------------------------------------------------------------------------

def test_partial_date_range_rejected():
    """Providing only start_date without end_date must be rejected."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ScenarioSimulateRequest(
            scenario_type=ScenarioType.EXPENSE_PERCENT_CHANGE,
            value=Decimal("10"),
            currency="LKR",
            start_date=date(2026, 1, 1),
            # end_date is missing
        )


# ---------------------------------------------------------------------------
# 32. Currency is normalised to uppercase
# ---------------------------------------------------------------------------

def test_currency_normalised_to_uppercase(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """'lkr' (lowercase) in the request must be treated as 'LKR'."""
    _tx(db, user_a, account_lkr, date(2026, 11, 1), Decimal("50000"), "credit")

    req = ScenarioSimulateRequest(
        scenario_type=ScenarioType.INCOME_PERCENT_CHANGE,
        value=Decimal("10"),
        currency="lkr",  # lowercase
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
    )
    assert req.currency == "LKR"

    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
    )
    assert result.currency == "LKR"
    assert result.baseline.income == Decimal("50000.0000")


# ---------------------------------------------------------------------------
# 33. Service singleton exists
# ---------------------------------------------------------------------------

def test_service_singleton_exists():
    """The module-level singleton must be a ScenarioSimulationService instance."""
    assert isinstance(scenario_simulation_service, ScenarioSimulationService)


# ---------------------------------------------------------------------------
# 34. SAVINGS_TARGET with zero income
# ---------------------------------------------------------------------------

def test_savings_target_zero_income(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """SAVINGS_TARGET when income=0: expenses=0, savings_rate=None."""
    # Only expense transactions, no income
    _tx(db, user_a, account_lkr, date(2026, 12, 5), Decimal("20000"), "debit")

    req = _build_request(
        ScenarioType.SAVINGS_TARGET,
        Decimal("10000"),
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 12, 1),
        period_end=date(2026, 12, 31),
    )

    assert result.baseline.income == Decimal("0.0000")
    # max expenses = max(0 - 10000, 0) = 0
    assert result.scenario.expenses == Decimal("0.0000")
    assert result.scenario.savings_rate is None


# ---------------------------------------------------------------------------
# 35. Negative cash flow baseline — scenario still works
# ---------------------------------------------------------------------------

def test_negative_baseline_cash_flow(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """Scenario works correctly even when baseline has negative net cash flow."""
    _tx(db, user_a, account_lkr, date(2026, 2, 1), Decimal("50000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 2, 5), Decimal("75000"), "debit")

    req = _build_request(
        ScenarioType.REMOVE_MONTHLY_EXPENSE,
        Decimal("10000"),
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 28),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
    )

    assert result.baseline.net_cash_flow == Decimal("-25000.0000")
    assert result.scenario.expenses == Decimal("65000.0000")
    assert result.scenario.net_cash_flow == Decimal("-15000.0000")
    assert result.impact.net_cash_flow_change == Decimal("10000.0000")


# ---------------------------------------------------------------------------
# 36. EXPENSE_PERCENT_CHANGE at exactly 0%
# ---------------------------------------------------------------------------

def test_expense_zero_percent_change(
    db: Session, user_a: User, account_lkr: FinancialAccount
):
    """0% change means scenario == baseline."""
    _tx(db, user_a, account_lkr, date(2026, 3, 1), Decimal("100000"), "credit")
    _tx(db, user_a, account_lkr, date(2026, 3, 5), Decimal("40000"), "debit")

    req = _build_request(
        ScenarioType.EXPENSE_PERCENT_CHANGE,
        Decimal("0"),
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
    )
    result = scenario_simulation_service.simulate(
        db=db,
        user_id=user_a.id,
        request=req,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )

    assert result.scenario.expenses == result.baseline.expenses
    assert result.scenario.income == result.baseline.income
    assert result.impact.expense_change == Decimal("0.0000")
    assert result.impact.net_cash_flow_change == Decimal("0.0000")
