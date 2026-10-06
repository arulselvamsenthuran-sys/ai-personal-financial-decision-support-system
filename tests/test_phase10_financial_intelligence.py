"""Comprehensive tests for Phase 10: Financial Intelligence & Analytics Engine.

Covers:
 1.  Income calculation (total, count, average, largest)
 2.  Expense calculation (total, count, average, largest)
 3.  Net cash flow calculation
 4.  Savings rate calculation
 5.  Zero-income handling (savings_rate must be None, not error)
 6.  Expense category breakdown (sorted, percentages)
 7.  Monthly aggregation (chronological, separate months)
 8.  Date-range filtering (transactions outside range excluded)
 9.  Recurring transaction detection (≥3 occurrences required)
10.  Spending change detection (absolute + percentage + direction)
11.  Multi-currency isolation (LKR + USD never aggregated)
12.  User ownership isolation (user B cannot see user A's analytics)
13.  Insight generation (correct types, severity, persistence)
14.  Decimal precision (no float arithmetic leakage)
15.  Existing Phase 1–9 tests still pass (implicit — this file only adds Phase 10)

Engineering invariants verified:
  - All monetary values are Decimal, never float.
  - Multi-currency: queries return per-currency results, never mixed.
  - User isolation: every service method scoped to user_id.
  - savings_rate is None (not zero) when income == 0.
  - Recurring detection requires ≥ 3 occurrences (configurable).
  - spending_change percentage_change is None when previous_amount == 0.
"""

from datetime import date, timedelta
from decimal import Decimal
import io
from typing import Generator
import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.financial_account import FinancialAccount
from app.models.financial_insight import FinancialInsight
from app.models.transaction import Transaction
from app.models.user import User
from app.services.document_service import document_ingestion_service
from app.services.financial_intelligence import (
    DateRange,
    FinancialIntelligenceService,
    _is_income,
    _is_expense,
    current_month_range,
    last_n_months_range,
    previous_month_range,
    financial_intelligence_service,
)
from app.services.insight_service import InsightService, insight_service


# ---------------------------------------------------------------------------
# Shared helpers and fixtures
# ---------------------------------------------------------------------------


class DummyUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "text/csv"):
        self.filename = filename
        self.file = io.BytesIO(content)
        self.content_type = content_type


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
    user = User(email=f"phase10_a_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user_b(db: Session) -> User:
    """Secondary user — must be invisible to user_a's analytics."""
    user = User(email=f"phase10_b_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def account_a(db: Session, user_a: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_a.id,
        name="Checking Account",
        account_type="bank",
        currency="LKR",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def account_b(db: Session, user_b: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=user_b.id,
        name="User B Account",
        account_type="bank",
        currency="USD",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _make_transaction(
    db: Session,
    user: User,
    account: FinancialAccount,
    tx_date: date,
    amount: Decimal,
    tx_type: str,
    category: str = None,
    merchant: str = None,
) -> Transaction:
    """Create and persist a single transaction."""
    tx = Transaction(
        user_id=user.id,
        financial_account_id=account.id,
        transaction_fingerprint=f"test_{uuid.uuid4().hex}",
        transaction_date=tx_date,
        amount=amount,
        currency=account.currency,
        transaction_type=tx_type,
        category=category,
        merchant=merchant,
        source="test",
    )
    db.add(tx)
    db.flush()
    return tx


# ---------------------------------------------------------------------------
# 1. Income calculation
# ---------------------------------------------------------------------------

def test_calculate_income_basic(db: Session, user_a: User, account_a: FinancialAccount):
    """Income is correctly summed from credit-type transactions."""
    _make_transaction(db, user_a, account_a, date(2026, 1, 10), Decimal("100000"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 1, 20), Decimal("50000"), "salary")
    _make_transaction(db, user_a, account_a, date(2026, 1, 15), Decimal("5000"), "debit")  # not income

    result = financial_intelligence_service.calculate_income(
        db, user_a.id, date(2026, 1, 1), date(2026, 1, 31)
    )

    assert "LKR" in result
    lkr = result["LKR"]
    assert lkr["total_income"] == Decimal("150000.0000")
    assert lkr["transaction_count"] == 2
    assert lkr["average_transaction"] == Decimal("75000.0000")
    assert lkr["largest_transaction"] == Decimal("100000.0000")


def test_calculate_income_no_income_transactions(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """When there are only expense transactions, income result is empty."""
    _make_transaction(db, user_a, account_a, date(2026, 2, 5), Decimal("3000"), "debit")

    result = financial_intelligence_service.calculate_income(
        db, user_a.id, date(2026, 2, 1), date(2026, 2, 28)
    )
    # LKR currency has no income transactions
    assert result.get("LKR") is None or len(result) == 0


# ---------------------------------------------------------------------------
# 2. Expense calculation
# ---------------------------------------------------------------------------

def test_calculate_expenses_basic(db: Session, user_a: User, account_a: FinancialAccount):
    """Expenses are correctly summed from debit-type transactions."""
    _make_transaction(db, user_a, account_a, date(2026, 3, 1), Decimal("25000"), "debit", "Rent")
    _make_transaction(db, user_a, account_a, date(2026, 3, 5), Decimal("5000"), "payment", "Food")
    _make_transaction(db, user_a, account_a, date(2026, 3, 15), Decimal("80000"), "credit")  # income

    result = financial_intelligence_service.calculate_expenses(
        db, user_a.id, date(2026, 3, 1), date(2026, 3, 31)
    )

    assert "LKR" in result
    lkr = result["LKR"]
    assert lkr["total_expenses"] == Decimal("30000.0000")
    assert lkr["transaction_count"] == 2
    assert lkr["average_transaction"] == Decimal("15000.0000")
    assert lkr["largest_transaction"] == Decimal("25000.0000")


# ---------------------------------------------------------------------------
# 3. Net cash flow
# ---------------------------------------------------------------------------

def test_calculate_net_cash_flow(db: Session, user_a: User, account_a: FinancialAccount):
    """Net cash flow = income - expenses."""
    _make_transaction(db, user_a, account_a, date(2026, 4, 1), Decimal("100000"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 4, 10), Decimal("65000"), "debit")

    result = financial_intelligence_service.calculate_net_cash_flow(
        db, user_a.id, date(2026, 4, 1), date(2026, 4, 30)
    )

    assert "LKR" in result
    lkr = result["LKR"]
    assert lkr["total_income"] == Decimal("100000.0000")
    assert lkr["total_expenses"] == Decimal("65000.0000")
    assert lkr["net_cash_flow"] == Decimal("35000.0000")


def test_negative_cash_flow(db: Session, user_a: User, account_a: FinancialAccount):
    """Net cash flow can be negative when expenses exceed income."""
    _make_transaction(db, user_a, account_a, date(2026, 5, 1), Decimal("50000"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 5, 10), Decimal("75000"), "debit")

    result = financial_intelligence_service.calculate_net_cash_flow(
        db, user_a.id, date(2026, 5, 1), date(2026, 5, 31)
    )

    assert result["LKR"]["net_cash_flow"] == Decimal("-25000.0000")


# ---------------------------------------------------------------------------
# 4. Savings rate
# ---------------------------------------------------------------------------

def test_savings_rate_positive(db: Session, user_a: User, account_a: FinancialAccount):
    """Savings rate = (income - expenses) / income * 100."""
    _make_transaction(db, user_a, account_a, date(2026, 6, 1), Decimal("100000"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 6, 10), Decimal("70000"), "debit")

    rates = financial_intelligence_service.calculate_savings_rate(
        db, user_a.id, date(2026, 6, 1), date(2026, 6, 30)
    )

    assert "LKR" in rates
    # (100000 - 70000) / 100000 * 100 = 30.00
    assert rates["LKR"] == Decimal("30.00")


# ---------------------------------------------------------------------------
# 5. Zero-income handling
# ---------------------------------------------------------------------------

def test_savings_rate_zero_income(db: Session, user_a: User, account_a: FinancialAccount):
    """Savings rate must be None (not raise an exception) when income is zero."""
    _make_transaction(db, user_a, account_a, date(2026, 7, 1), Decimal("20000"), "debit")

    result = financial_intelligence_service.calculate_net_cash_flow(
        db, user_a.id, date(2026, 7, 1), date(2026, 7, 31)
    )

    # Savings rate must be None (not division by zero error)
    assert result["LKR"]["savings_rate"] is None


def test_savings_rate_helper_zero_income(db: Session, user_a: User, account_a: FinancialAccount):
    """calculate_savings_rate returns None per currency when income is 0."""
    _make_transaction(db, user_a, account_a, date(2026, 7, 5), Decimal("5000"), "debit")

    rates = financial_intelligence_service.calculate_savings_rate(
        db, user_a.id, date(2026, 7, 1), date(2026, 7, 31)
    )
    assert rates.get("LKR") is None


# ---------------------------------------------------------------------------
# 6. Category breakdown
# ---------------------------------------------------------------------------

def test_expense_category_breakdown(db: Session, user_a: User, account_a: FinancialAccount):
    """Categories are returned sorted descending with correct percentages."""
    _make_transaction(db, user_a, account_a, date(2026, 8, 1), Decimal("60000"), "debit", "Rent")
    _make_transaction(db, user_a, account_a, date(2026, 8, 5), Decimal("20000"), "debit", "Food")
    _make_transaction(db, user_a, account_a, date(2026, 8, 10), Decimal("20000"), "debit", "Food")
    _make_transaction(db, user_a, account_a, date(2026, 8, 15), Decimal("20000"), "debit", None)  # Uncategorized

    result = financial_intelligence_service.calculate_expense_breakdown(
        db, user_a.id, date(2026, 8, 1), date(2026, 8, 31)
    )

    assert "LKR" in result
    categories = result["LKR"]
    # Total = 120000
    # Rent: 60000 = 50%, Food: 40000 = 33.33%, Uncategorized: 20000 = 16.67%
    assert len(categories) == 3

    # Sorted descending
    assert categories[0]["category"] == "Rent"
    assert categories[0]["amount"] == Decimal("60000.0000")
    assert categories[0]["percentage"] == Decimal("50.00")

    assert categories[1]["category"] == "Food"
    assert categories[1]["amount"] == Decimal("40000.0000")

    assert categories[2]["category"] == "Uncategorized"


def test_null_category_bucketed_as_uncategorized(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Transactions with no category must appear as 'Uncategorized'."""
    _make_transaction(db, user_a, account_a, date(2026, 8, 20), Decimal("5000"), "debit", None)

    result = financial_intelligence_service.calculate_expense_breakdown(
        db, user_a.id, date(2026, 8, 1), date(2026, 8, 31)
    )
    cats = {c["category"] for c in result.get("LKR", [])}
    assert "Uncategorized" in cats


# ---------------------------------------------------------------------------
# 7. Monthly aggregation
# ---------------------------------------------------------------------------

def test_monthly_cash_flow_chronological(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Monthly data is returned in chronological (year, month) order."""
    _make_transaction(db, user_a, account_a, date(2026, 1, 10), Decimal("100000"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 2, 10), Decimal("110000"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 1, 20), Decimal("65000"), "debit")
    _make_transaction(db, user_a, account_a, date(2026, 2, 20), Decimal("72000"), "debit")

    result = financial_intelligence_service.calculate_monthly_cash_flow(
        db, user_a.id, date(2026, 1, 1), date(2026, 2, 28)
    )

    # Filter to LKR only
    lkr_months = [r for r in result if r["currency"] == "LKR"]
    assert len(lkr_months) == 2

    jan = lkr_months[0]
    feb = lkr_months[1]

    assert jan["year"] == 2026 and jan["month"] == 1
    assert jan["income"] == Decimal("100000.0000")
    assert jan["expenses"] == Decimal("65000.0000")
    assert jan["net_cash_flow"] == Decimal("35000.0000")

    assert feb["year"] == 2026 and feb["month"] == 2
    assert feb["income"] == Decimal("110000.0000")
    assert feb["expenses"] == Decimal("72000.0000")
    assert feb["net_cash_flow"] == Decimal("38000.0000")


# ---------------------------------------------------------------------------
# 8. Date-range filtering
# ---------------------------------------------------------------------------

def test_date_range_filtering_excludes_outside(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Transactions outside the date range must NOT appear in results."""
    # Inside range
    _make_transaction(db, user_a, account_a, date(2026, 3, 15), Decimal("50000"), "credit")
    # Outside range — before
    _make_transaction(db, user_a, account_a, date(2026, 2, 28), Decimal("20000"), "credit")
    # Outside range — after
    _make_transaction(db, user_a, account_a, date(2026, 4, 1), Decimal("30000"), "credit")

    result = financial_intelligence_service.calculate_income(
        db, user_a.id, date(2026, 3, 1), date(2026, 3, 31)
    )

    assert "LKR" in result
    assert result["LKR"]["total_income"] == Decimal("50000.0000")
    assert result["LKR"]["transaction_count"] == 1


def test_date_range_helper_current_month():
    """current_month_range() start ≤ today ≤ end."""
    dr = current_month_range()
    today = date.today()
    assert dr.start <= today <= dr.end
    assert dr.start.day == 1


def test_date_range_helper_previous_month():
    """previous_month_range() covers the entire previous calendar month."""
    dr = previous_month_range()
    today = date.today()
    assert dr.end < today.replace(day=1)
    assert dr.start.day == 1


# ---------------------------------------------------------------------------
# 9. Recurring transaction detection
# ---------------------------------------------------------------------------

def test_recurring_detection_requires_min_occurrences(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Recurring detection must NOT flag merchants with only 1–2 occurrences."""
    # Only 2 occurrences — should NOT be flagged
    _make_transaction(
        db, user_a, account_a, date(2026, 1, 5), Decimal("5000"), "debit",
        merchant="SingleMerchant"
    )
    _make_transaction(
        db, user_a, account_a, date(2026, 2, 5), Decimal("5000"), "debit",
        merchant="SingleMerchant"
    )

    patterns = financial_intelligence_service.detect_recurring_transactions(
        db, user_a.id, min_occurrences=3
    )
    merchant_names = [p["merchant"] for p in patterns]
    assert "SingleMerchant" not in merchant_names


def test_recurring_detection_flags_consistent_monthly(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Recurring detection must flag a merchant with ≥3 consistent monthly transactions."""
    for month in [1, 2, 3]:
        _make_transaction(
            db, user_a, account_a,
            date(2026, month, 5),
            Decimal("9999"),
            "debit",
            merchant="Netflix"
        )

    patterns = financial_intelligence_service.detect_recurring_transactions(
        db, user_a.id, min_occurrences=3
    )
    merchants = [p["merchant"] for p in patterns]
    assert "Netflix" in merchants

    netflix = next(p for p in patterns if p["merchant"] == "Netflix")
    assert netflix["occurrence_count"] == 3
    assert netflix["detected_frequency"] == "monthly"


def test_recurring_detection_handles_similar_amounts(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Transactions with amounts within 10% tolerance are treated as the same recurring expense."""
    amounts = [Decimal("9999"), Decimal("10050"), Decimal("9980")]
    for i, amt in enumerate(amounts):
        _make_transaction(
            db, user_a, account_a,
            date(2026, i + 1, 10),
            amt,
            "debit",
            merchant="Spotify"
        )

    patterns = financial_intelligence_service.detect_recurring_transactions(
        db, user_a.id, min_occurrences=3
    )
    merchants = [p["merchant"] for p in patterns]
    assert "Spotify" in merchants


# ---------------------------------------------------------------------------
# 10. Spending change detection
# ---------------------------------------------------------------------------

def test_spending_change_detection(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """detect_spending_changes returns correct direction, absolute, and percentage change."""
    # Previous month: Food = 10000
    _make_transaction(
        db, user_a, account_a, date(2026, 1, 10), Decimal("10000"), "debit", "Food"
    )
    # Current month: Food = 15000
    _make_transaction(
        db, user_a, account_a, date(2026, 2, 10), Decimal("15000"), "debit", "Food"
    )

    changes = financial_intelligence_service.detect_spending_changes(
        db,
        user_a.id,
        current_start=date(2026, 2, 1),
        current_end=date(2026, 2, 28),
        previous_start=date(2026, 1, 1),
        previous_end=date(2026, 1, 31),
    )

    food_changes = [c for c in changes if c["category"] == "Food"]
    assert len(food_changes) == 1

    fc = food_changes[0]
    assert fc["previous_amount"] == Decimal("10000.0000")
    assert fc["current_amount"] == Decimal("15000.0000")
    assert fc["absolute_change"] == Decimal("5000.0000")
    assert fc["percentage_change"] == Decimal("50.00")
    assert fc["direction"] == "increased"


def test_spending_change_zero_previous_amount(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """percentage_change must be None when previous_amount is zero (new category)."""
    _make_transaction(
        db, user_a, account_a, date(2026, 4, 10), Decimal("8000"), "debit", "NewCategory"
    )

    changes = financial_intelligence_service.detect_spending_changes(
        db,
        user_a.id,
        current_start=date(2026, 4, 1),
        current_end=date(2026, 4, 30),
        previous_start=date(2026, 3, 1),
        previous_end=date(2026, 3, 31),
    )

    new_cat = next((c for c in changes if c["category"] == "NewCategory"), None)
    assert new_cat is not None
    assert new_cat["percentage_change"] is None
    assert new_cat["absolute_change"] == Decimal("8000.0000")


# ---------------------------------------------------------------------------
# 11. Multi-currency isolation
# ---------------------------------------------------------------------------

def test_multi_currency_never_aggregated(db: Session, user_a: User):
    """LKR and USD transactions must appear as separate entries, never summed."""
    # Create two accounts with different currencies
    lkr_account = FinancialAccount(
        user_id=user_a.id, name="LKR Account", account_type="bank", currency="LKR"
    )
    usd_account = FinancialAccount(
        user_id=user_a.id, name="USD Account", account_type="bank", currency="USD"
    )
    db.add_all([lkr_account, usd_account])
    db.commit()
    db.refresh(lkr_account)
    db.refresh(usd_account)

    # LKR income
    _make_transaction(db, user_a, lkr_account, date(2026, 6, 1), Decimal("115000"), "credit")
    _make_transaction(db, user_a, lkr_account, date(2026, 6, 5), Decimal("9500"), "debit")
    # USD income
    _make_transaction(db, user_a, usd_account, date(2026, 6, 1), Decimal("1000"), "credit")
    _make_transaction(db, user_a, usd_account, date(2026, 6, 5), Decimal("200"), "debit")

    result = financial_intelligence_service.calculate_net_cash_flow(
        db, user_a.id, date(2026, 6, 1), date(2026, 6, 30)
    )

    # Must have exactly two currency keys
    assert "LKR" in result
    assert "USD" in result
    assert len(result) == 2

    # LKR values must be correct and independent
    assert result["LKR"]["total_income"] == Decimal("115000.0000")
    assert result["LKR"]["total_expenses"] == Decimal("9500.0000")

    # USD values must be correct and independent
    assert result["USD"]["total_income"] == Decimal("1000.0000")
    assert result["USD"]["total_expenses"] == Decimal("200.0000")

    # Critical: LKR income != USD income (no cross-currency pollution)
    assert result["LKR"]["total_income"] != result["USD"]["total_income"]


def test_currency_filter_isolates_single_currency(db: Session, user_a: User):
    """Passing currency='LKR' must exclude USD results entirely."""
    lkr_account = FinancialAccount(
        user_id=user_a.id, name="LKR2", account_type="bank", currency="LKR"
    )
    usd_account = FinancialAccount(
        user_id=user_a.id, name="USD2", account_type="bank", currency="USD"
    )
    db.add_all([lkr_account, usd_account])
    db.commit()
    db.refresh(lkr_account)
    db.refresh(usd_account)

    _make_transaction(db, user_a, lkr_account, date(2026, 7, 1), Decimal("50000"), "credit")
    _make_transaction(db, user_a, usd_account, date(2026, 7, 1), Decimal("500"), "credit")

    result = financial_intelligence_service.calculate_income(
        db, user_a.id, date(2026, 7, 1), date(2026, 7, 31), currency="LKR"
    )

    assert "LKR" in result
    assert "USD" not in result


# ---------------------------------------------------------------------------
# 12. User ownership isolation
# ---------------------------------------------------------------------------

def test_user_ownership_isolation(
    db: Session,
    user_a: User,
    account_a: FinancialAccount,
    user_b: User,
    account_b: FinancialAccount,
):
    """User B must not see User A's transactions in analytics."""
    # User A has LKR income
    _make_transaction(db, user_a, account_a, date(2026, 8, 1), Decimal("100000"), "credit")
    # User B has USD income
    _make_transaction(db, user_b, account_b, date(2026, 8, 1), Decimal("999"), "credit")

    result_a = financial_intelligence_service.calculate_income(
        db, user_a.id, date(2026, 8, 1), date(2026, 8, 31)
    )
    result_b = financial_intelligence_service.calculate_income(
        db, user_b.id, date(2026, 8, 1), date(2026, 8, 31)
    )

    # User A only sees LKR, not USD
    assert "LKR" in result_a
    assert "USD" not in result_a

    # User B only sees USD, not LKR
    assert "USD" in result_b
    assert "LKR" not in result_b

    # User A's income is correct
    assert result_a["LKR"]["total_income"] == Decimal("100000.0000")

    # User B's income is correct — not contaminated by user A's data
    assert result_b["USD"]["total_income"] == Decimal("999.0000")


# ---------------------------------------------------------------------------
# 13. Insight generation
# ---------------------------------------------------------------------------

def test_insight_negative_cash_flow_generated(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """NEGATIVE_CASH_FLOW insight must be created when expenses > income."""
    _make_transaction(db, user_a, account_a, date(2026, 9, 1), Decimal("30000"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 9, 5), Decimal("50000"), "debit")

    insights = insight_service.generate_summary_insights(
        db, user_a.id, date(2026, 9, 1), date(2026, 9, 30)
    )

    types = [i.insight_type for i in insights]
    assert "NEGATIVE_CASH_FLOW" in types

    neg_flow = next(i for i in insights if i.insight_type == "NEGATIVE_CASH_FLOW")
    assert neg_flow.severity == "ALERT"
    assert neg_flow.user_id == user_a.id
    assert neg_flow.currency == "LKR"


def test_insight_high_expense_category_generated(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """HIGH_EXPENSE_CATEGORY insight must be created when a category ≥ 30% of expenses."""
    _make_transaction(db, user_a, account_a, date(2026, 10, 1), Decimal("60000"), "debit", "Rent")
    _make_transaction(db, user_a, account_a, date(2026, 10, 5), Decimal("10000"), "debit", "Food")
    _make_transaction(db, user_a, account_a, date(2026, 10, 10), Decimal("10000"), "debit", "Transport")
    # Rent = 60000 / 80000 = 75% → exceeds 30% threshold

    insights = insight_service.generate_summary_insights(
        db, user_a.id, date(2026, 10, 1), date(2026, 10, 31)
    )

    types = [i.insight_type for i in insights]
    assert "HIGH_EXPENSE_CATEGORY" in types

    hec = next(i for i in insights if i.insight_type == "HIGH_EXPENSE_CATEGORY")
    assert "Rent" in hec.title


def test_insight_user_isolation(
    db: Session,
    user_a: User,
    account_a: FinancialAccount,
    user_b: User,
    account_b: FinancialAccount,
):
    """Insights for user A must not be visible to user B's insight query."""
    _make_transaction(db, user_a, account_a, date(2026, 11, 1), Decimal("10000"), "debit")

    insight_service.generate_summary_insights(
        db, user_a.id, date(2026, 11, 1), date(2026, 11, 30)
    )

    # User B retrieves insights — should be empty
    b_insights = insight_service.get_insights(db, user_b.id)
    assert len(b_insights) == 0


def test_insight_persisted_to_database(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Generated insights must be persisted to financial_insights table."""
    _make_transaction(db, user_a, account_a, date(2026, 11, 5), Decimal("20000"), "debit")

    generated = insight_service.generate_summary_insights(
        db, user_a.id, date(2026, 11, 1), date(2026, 11, 30)
    )
    db.flush()

    stored = (
        db.query(FinancialInsight)
        .filter(FinancialInsight.user_id == user_a.id)
        .all()
    )
    assert len(stored) >= len(generated)


def test_insight_large_transaction_generated(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """LARGE_TRANSACTION insight generated when tx ≥ 3× average expense."""
    # Average of first two = 5000; third = 20000 = 4× → must be flagged
    _make_transaction(db, user_a, account_a, date(2026, 12, 1), Decimal("5000"), "debit", "Food")
    _make_transaction(db, user_a, account_a, date(2026, 12, 5), Decimal("5000"), "debit", "Transport")
    _make_transaction(db, user_a, account_a, date(2026, 12, 10), Decimal("20000"), "debit", "Emergency")

    insights = insight_service.generate_summary_insights(
        db, user_a.id, date(2026, 12, 1), date(2026, 12, 31)
    )

    types = [i.insight_type for i in insights]
    assert "LARGE_TRANSACTION" in types


# ---------------------------------------------------------------------------
# 14. Decimal precision
# ---------------------------------------------------------------------------

def test_decimal_precision_no_float_leakage(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """All monetary results must be Decimal instances, never float."""
    _make_transaction(db, user_a, account_a, date(2026, 1, 1), Decimal("33333.3333"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 1, 2), Decimal("11111.1111"), "debit")

    result = financial_intelligence_service.calculate_net_cash_flow(
        db, user_a.id, date(2026, 1, 1), date(2026, 1, 31)
    )

    lkr = result["LKR"]
    assert isinstance(lkr["total_income"], Decimal), "total_income must be Decimal"
    assert isinstance(lkr["total_expenses"], Decimal), "total_expenses must be Decimal"
    assert isinstance(lkr["net_cash_flow"], Decimal), "net_cash_flow must be Decimal"
    # savings_rate may be None when income is zero, but when present must be Decimal
    if lkr["savings_rate"] is not None:
        assert isinstance(lkr["savings_rate"], Decimal), "savings_rate must be Decimal"


def test_savings_rate_decimal_precision(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Savings rate calculation must use Decimal with ROUND_HALF_UP."""
    _make_transaction(db, user_a, account_a, date(2026, 2, 1), Decimal("300"), "credit")
    _make_transaction(db, user_a, account_a, date(2026, 2, 2), Decimal("100"), "debit")

    rates = financial_intelligence_service.calculate_savings_rate(
        db, user_a.id, date(2026, 2, 1), date(2026, 2, 28)
    )

    # (300 - 100) / 300 * 100 = 66.666... → ROUND_HALF_UP → 66.67
    assert rates["LKR"] == Decimal("66.67")


def test_expense_breakdown_percentage_decimal(
    db: Session, user_a: User, account_a: FinancialAccount
):
    """Expense percentage must be a Decimal rounded to 2 decimal places."""
    _make_transaction(db, user_a, account_a, date(2026, 3, 1), Decimal("1"), "debit", "A")
    _make_transaction(db, user_a, account_a, date(2026, 3, 2), Decimal("2"), "debit", "B")
    _make_transaction(db, user_a, account_a, date(2026, 3, 3), Decimal("3"), "debit", "C")

    result = financial_intelligence_service.calculate_expense_breakdown(
        db, user_a.id, date(2026, 3, 1), date(2026, 3, 31)
    )

    for cat in result.get("LKR", []):
        assert isinstance(cat["percentage"], Decimal)
        # Should have at most 2 decimal places
        assert cat["percentage"] == cat["percentage"].quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# 15. DateRange validation
# ---------------------------------------------------------------------------

def test_date_range_rejects_invalid_range():
    """DateRange must raise ValueError when start > end."""
    with pytest.raises(ValueError):
        DateRange(date(2026, 12, 31), date(2026, 1, 1))


def test_date_range_valid():
    """DateRange accepts start == end (single day)."""
    dr = DateRange(date(2026, 6, 15), date(2026, 6, 15))
    assert dr.start == dr.end


# ---------------------------------------------------------------------------
# 16. Transaction type classification helpers
# ---------------------------------------------------------------------------

def test_income_classification():
    """_is_income correctly identifies credit-type transactions."""
    for tx_type in ["credit", "income", "deposit", "salary", "transfer_in"]:
        assert _is_income(tx_type), f"Expected {tx_type!r} to be income"


def test_expense_classification():
    """_is_expense correctly identifies debit-type transactions."""
    for tx_type in ["debit", "expense", "withdrawal", "payment", "transfer_out", "unknown"]:
        assert _is_expense(tx_type), f"Expected {tx_type!r} to be expense"
