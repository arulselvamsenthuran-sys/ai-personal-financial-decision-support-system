"""Financial Intelligence Service — Phase 10.

Provides deterministic financial analytics over a user's transaction data.

Engineering rules:
  - All monetary arithmetic uses Decimal (never float).
  - All queries are scoped by user_id (IDOR prevention).
  - Multi-currency data is NEVER aggregated across currencies.
  - Results are grouped by currency.
  - Date ranges are explicit UTC-based dates.
  - No LLM, no ML, no financial advice is produced.

Phase 10 produces deterministic financial observations.
It does not provide financial advice.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.transaction import Transaction

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mirror of ledger_service classification — keep in sync
_CREDIT_TYPES: frozenset[str] = frozenset(
    {"credit", "income", "deposit", "salary", "transfer_in"}
)
_DEBIT_TYPES: frozenset[str] = frozenset(
    {"debit", "expense", "withdrawal", "payment", "transfer_out"}
)

# Minimum occurrences before a transaction is reported as "recurring"
_RECURRING_MIN_OCCURRENCES: int = 3

# Amount tolerance: two amounts are "similar" if they differ by ≤ this fraction
_RECURRING_AMOUNT_TOLERANCE: Decimal = Decimal("0.10")  # 10 %

# High-expense category threshold: category is flagged when it represents ≥ this % of total expenses
HIGH_CATEGORY_THRESHOLD_PCT: Decimal = Decimal("30")

# Large-transaction threshold multiplier vs. the user's average expense
LARGE_TX_MULTIPLIER: Decimal = Decimal("3")

# Significant spending-change threshold (percentage points)
SIGNIFICANT_CHANGE_PCT: Decimal = Decimal("20")


def _two_dp(value: Decimal) -> Decimal:
    """Round to 2 decimal places (ROUND_HALF_UP)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _four_dp(value: Decimal) -> Decimal:
    """Round to 4 decimal places (ROUND_HALF_UP)."""
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _is_income(tx_type: str) -> bool:
    return (tx_type or "").strip().lower() in _CREDIT_TYPES


def _is_expense(tx_type: str) -> bool:
    return not _is_income(tx_type)


# ---------------------------------------------------------------------------
# Date-range helper
# ---------------------------------------------------------------------------

class DateRange:
    """Represents a closed [start, end] date interval."""

    def __init__(self, start: date, end: date) -> None:
        if start > end:
            raise ValueError(
                f"start_date ({start}) must not be after end_date ({end})"
            )
        self.start = start
        self.end = end

    def __repr__(self) -> str:  # pragma: no cover
        return f"DateRange({self.start} → {self.end})"


def current_month_range() -> DateRange:
    """Return a DateRange covering the current UTC calendar month."""
    today = date.today()
    start = today.replace(day=1)
    # Last day of month: first day of next month minus 1 day
    if today.month == 12:
        end = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(today.year, today.month + 1, 1) - timedelta(days=1)
    return DateRange(start, end)


def previous_month_range() -> DateRange:
    """Return a DateRange covering the previous UTC calendar month."""
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_of_prev = first_of_this_month - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)
    return DateRange(first_of_prev, last_of_prev)


def last_n_months_range(n: int) -> DateRange:
    """Return a DateRange covering the last n complete calendar months + current month-to-date."""
    today = date.today()
    # Go back n months from start of current month
    month = today.month - n
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    start = date(year, month, 1)
    return DateRange(start, today)


# ---------------------------------------------------------------------------
# Core financial intelligence service
# ---------------------------------------------------------------------------

class FinancialIntelligenceService:
    """Deterministic financial analytics engine.

    All public methods require `user_id` to enforce data isolation.
    Multi-currency: metrics are grouped by currency and never cross-aggregated.
    """

    # ------------------------------------------------------------------
    # 1. Income analysis
    # ------------------------------------------------------------------

    def calculate_income(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Calculate income metrics for the user within [start_date, end_date].

        Returns a dict keyed by currency:
        {
            "LKR": {
                "total_income": Decimal,
                "transaction_count": int,
                "average_transaction": Decimal,
                "largest_transaction": Decimal,
            }, ...
        }
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            )
        )
        if currency:
            q = q.filter(Transaction.currency == currency.upper())

        transactions = q.all()
        income_txns = [t for t in transactions if _is_income(t.transaction_type)]

        return self._aggregate_income_transactions(income_txns)

    def _aggregate_income_transactions(
        self, txns: List[Transaction]
    ) -> Dict[str, Any]:
        """Group income transactions by currency and compute metrics."""
        by_currency: Dict[str, list[Decimal]] = defaultdict(list)
        for tx in txns:
            by_currency[tx.currency].append(Decimal(str(tx.amount)))

        result: Dict[str, Any] = {}
        for cur, amounts in by_currency.items():
            total = _four_dp(sum(amounts, Decimal("0")))
            count = len(amounts)
            avg = _four_dp(total / count) if count > 0 else Decimal("0")
            largest = _four_dp(max(amounts)) if amounts else Decimal("0")
            result[cur] = {
                "total_income": total,
                "transaction_count": count,
                "average_transaction": avg,
                "largest_transaction": largest,
            }
        return result

    # ------------------------------------------------------------------
    # 2. Expense analysis
    # ------------------------------------------------------------------

    def calculate_expenses(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Calculate expense metrics for the user within [start_date, end_date].

        Returns a dict keyed by currency with total, count, average, largest.
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            )
        )
        if currency:
            q = q.filter(Transaction.currency == currency.upper())

        transactions = q.all()
        expense_txns = [t for t in transactions if _is_expense(t.transaction_type)]

        return self._aggregate_expense_transactions(expense_txns)

    def _aggregate_expense_transactions(
        self, txns: List[Transaction]
    ) -> Dict[str, Any]:
        """Group expense transactions by currency and compute metrics."""
        by_currency: Dict[str, list[Decimal]] = defaultdict(list)
        for tx in txns:
            by_currency[tx.currency].append(Decimal(str(tx.amount)))

        result: Dict[str, Any] = {}
        for cur, amounts in by_currency.items():
            total = _four_dp(sum(amounts, Decimal("0")))
            count = len(amounts)
            avg = _four_dp(total / count) if count > 0 else Decimal("0")
            largest = _four_dp(max(amounts)) if amounts else Decimal("0")
            result[cur] = {
                "total_expenses": total,
                "transaction_count": count,
                "average_transaction": avg,
                "largest_transaction": largest,
            }
        return result

    # ------------------------------------------------------------------
    # 3. Net cash flow + savings rate
    # ------------------------------------------------------------------

    def calculate_net_cash_flow(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Calculate net cash flow per currency.

        net_cash_flow = total_income - total_expenses
        savings_rate  = net_cash_flow / total_income * 100  (None when income == 0)

        Returns dict keyed by currency.
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            )
        )
        if currency:
            q = q.filter(Transaction.currency == currency.upper())

        transactions = q.all()
        return self._compute_cash_flow_by_currency(transactions)

    def _compute_cash_flow_by_currency(
        self, txns: List[Transaction]
    ) -> Dict[str, Any]:
        """Partition transactions by currency, compute flow + savings rate."""
        by_currency: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"income": Decimal("0"), "expenses": Decimal("0"),
                     "income_count": 0, "expense_count": 0}
        )
        for tx in txns:
            cur = tx.currency
            amt = Decimal(str(tx.amount))
            if _is_income(tx.transaction_type):
                by_currency[cur]["income"] += amt
                by_currency[cur]["income_count"] += 1
            else:
                by_currency[cur]["expenses"] += amt
                by_currency[cur]["expense_count"] += 1

        result: Dict[str, Any] = {}
        for cur, data in by_currency.items():
            income = _four_dp(data["income"])
            expenses = _four_dp(data["expenses"])
            net = _four_dp(income - expenses)
            savings_rate: Optional[Decimal] = None
            if income > Decimal("0"):
                savings_rate = _two_dp(net / income * Decimal("100"))

            result[cur] = {
                "total_income": income,
                "total_expenses": expenses,
                "net_cash_flow": net,
                "savings_rate": savings_rate,
                "income_transaction_count": data["income_count"],
                "expense_transaction_count": data["expense_count"],
                "transaction_count": data["income_count"] + data["expense_count"],
            }
        return result

    def calculate_savings_rate(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> Dict[str, Optional[Decimal]]:
        """Return savings rate (%) per currency. None when income is zero."""
        flow = self.calculate_net_cash_flow(
            db, user_id, start_date, end_date, currency
        )
        return {cur: data["savings_rate"] for cur, data in flow.items()}

    # ------------------------------------------------------------------
    # 4. Expense category breakdown
    # ------------------------------------------------------------------

    def calculate_expense_breakdown(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return expense amounts grouped by category, sorted descending.

        Missing / null categories → "Uncategorized".

        Returns dict keyed by currency:
        {
            "LKR": [
                {"category": "Food", "amount": Decimal, "transaction_count": int, "percentage": Decimal},
                ...
            ]
        }
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            )
        )
        if currency:
            q = q.filter(Transaction.currency == currency.upper())

        transactions = q.all()
        expense_txns = [t for t in transactions if _is_expense(t.transaction_type)]

        # Accumulate per (currency, category)
        cat_map: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
            lambda: {"amount": Decimal("0"), "count": 0}
        )
        totals_by_currency: Dict[str, Decimal] = defaultdict(Decimal)

        for tx in expense_txns:
            cat = tx.category if tx.category else "Uncategorized"
            key = (tx.currency, cat)
            amt = Decimal(str(tx.amount))
            cat_map[key]["amount"] += amt
            cat_map[key]["count"] += 1
            totals_by_currency[tx.currency] += amt

        # Build result grouped by currency
        result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for (cur, cat), data in cat_map.items():
            total = totals_by_currency[cur]
            pct = (
                _two_dp(data["amount"] / total * Decimal("100"))
                if total > Decimal("0")
                else Decimal("0.00")
            )
            result[cur].append(
                {
                    "category": cat,
                    "amount": _four_dp(data["amount"]),
                    "transaction_count": data["count"],
                    "percentage": pct,
                }
            )

        # Sort each currency list by amount descending
        for cur in result:
            result[cur].sort(key=lambda x: x["amount"], reverse=True)

        return dict(result)

    # ------------------------------------------------------------------
    # 5. Monthly aggregates
    # ------------------------------------------------------------------

    def calculate_monthly_cash_flow(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return monthly income / expenses / net per currency, chronological.

        Each item in the list:
        {
            "year": int, "month": int, "currency": str,
            "income": Decimal, "expenses": Decimal, "net_cash_flow": Decimal,
            "income_transaction_count": int, "expense_transaction_count": int,
        }
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            )
        )
        if currency:
            q = q.filter(Transaction.currency == currency.upper())

        transactions = q.all()

        # Accumulate per (year, month, currency)
        monthly: Dict[Tuple[int, int, str], Dict[str, Any]] = defaultdict(
            lambda: {"income": Decimal("0"), "expenses": Decimal("0"),
                     "income_count": 0, "expense_count": 0}
        )
        for tx in transactions:
            key = (tx.transaction_date.year, tx.transaction_date.month, tx.currency)
            amt = Decimal(str(tx.amount))
            if _is_income(tx.transaction_type):
                monthly[key]["income"] += amt
                monthly[key]["income_count"] += 1
            else:
                monthly[key]["expenses"] += amt
                monthly[key]["expense_count"] += 1

        # Build sorted result list
        result: List[Dict[str, Any]] = []
        for (year, month, cur), data in sorted(monthly.items()):
            income = _four_dp(data["income"])
            expenses = _four_dp(data["expenses"])
            result.append(
                {
                    "year": year,
                    "month": month,
                    "currency": cur,
                    "income": income,
                    "expenses": expenses,
                    "net_cash_flow": _four_dp(income - expenses),
                    "income_transaction_count": data["income_count"],
                    "expense_transaction_count": data["expense_count"],
                }
            )
        return result

    def calculate_monthly_expense_trends(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return monthly expense-by-category data for trend analysis.

        Each item: {"year", "month", "currency", "category", "amount", "transaction_count"}
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            )
        )
        if currency:
            q = q.filter(Transaction.currency == currency.upper())

        transactions = [
            t for t in q.all() if _is_expense(t.transaction_type)
        ]

        # Accumulate per (year, month, currency, category)
        trend: Dict[Tuple[int, int, str, str], Dict[str, Any]] = defaultdict(
            lambda: {"amount": Decimal("0"), "count": 0}
        )
        for tx in transactions:
            cat = tx.category if tx.category else "Uncategorized"
            key = (tx.transaction_date.year, tx.transaction_date.month, tx.currency, cat)
            trend[key]["amount"] += Decimal(str(tx.amount))
            trend[key]["count"] += 1

        result: List[Dict[str, Any]] = []
        for (year, month, cur, cat), data in sorted(trend.items()):
            result.append(
                {
                    "year": year,
                    "month": month,
                    "currency": cur,
                    "category": cat,
                    "amount": _four_dp(data["amount"]),
                    "transaction_count": data["count"],
                }
            )
        return result

    # ------------------------------------------------------------------
    # 6. Recurring transaction detection
    # ------------------------------------------------------------------

    def detect_recurring_transactions(
        self,
        db: Session,
        user_id: uuid.UUID,
        currency: Optional[str] = None,
        min_occurrences: int = _RECURRING_MIN_OCCURRENCES,
    ) -> List[Dict[str, Any]]:
        """Detect recurring expense transactions deterministically.

        Detection algorithm:
          1. Group expense transactions by (merchant, currency).
          2. Exclude groups with < min_occurrences transactions.
          3. Within each group, cluster by approximate amount (± TOLERANCE).
          4. For clusters meeting the occurrence threshold, compute average
             days between occurrences.
          5. Classify frequency: monthly (25–35 days avg), bi-monthly (50–70),
             else irregular.

        Note: This reports *detected patterns*, not guaranteed recurrences.
        Requires at least {min_occurrences} occurrences before flagging.
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.merchant.isnot(None),
            )
        )
        if currency:
            q = q.filter(Transaction.currency == currency.upper())

        transactions = [t for t in q.all() if _is_expense(t.transaction_type)]

        # Group by (merchant, currency)
        merchant_groups: Dict[Tuple[str, str], List[Transaction]] = defaultdict(list)
        for tx in transactions:
            if tx.merchant:
                merchant_groups[(tx.merchant.strip(), tx.currency)].append(tx)

        patterns: List[Dict[str, Any]] = []

        for (merchant, cur), txns in merchant_groups.items():
            if len(txns) < min_occurrences:
                continue

            # Sort by date
            txns_sorted = sorted(txns, key=lambda t: t.transaction_date)

            # Cluster by approximate amount
            clusters = self._cluster_by_amount(txns_sorted)

            for cluster in clusters:
                if len(cluster) < min_occurrences:
                    continue

                amounts = [Decimal(str(t.amount)) for t in cluster]
                avg_amount = _four_dp(
                    sum(amounts, Decimal("0")) / len(amounts)
                )
                dates = [t.transaction_date for t in cluster]
                last_date = max(dates)

                avg_days = self._compute_average_days_between(dates)
                frequency = self._classify_frequency(avg_days)

                patterns.append(
                    {
                        "currency": cur,
                        "merchant": merchant,
                        "approximate_amount": avg_amount,
                        "occurrence_count": len(cluster),
                        "detected_frequency": frequency,
                        "last_occurrence": last_date,
                        "average_days_between": (
                            _two_dp(avg_days) if avg_days is not None else None
                        ),
                    }
                )

        # Sort by occurrence count descending
        patterns.sort(key=lambda p: p["occurrence_count"], reverse=True)
        return patterns

    def _cluster_by_amount(
        self, txns: List[Transaction]
    ) -> List[List[Transaction]]:
        """Group transactions into clusters with similar amounts (greedy).

        Two amounts are "similar" when
            |a - b| / max(a, b) <= _RECURRING_AMOUNT_TOLERANCE
        """
        clusters: List[List[Transaction]] = []
        used = [False] * len(txns)

        for i, tx in enumerate(txns):
            if used[i]:
                continue
            cluster = [tx]
            used[i] = True
            amt_i = Decimal(str(tx.amount))

            for j in range(i + 1, len(txns)):
                if used[j]:
                    continue
                amt_j = Decimal(str(txns[j].amount))
                max_amt = max(amt_i, amt_j)
                if max_amt == Decimal("0"):
                    cluster.append(txns[j])
                    used[j] = True
                else:
                    diff_ratio = abs(amt_i - amt_j) / max_amt
                    if diff_ratio <= _RECURRING_AMOUNT_TOLERANCE:
                        cluster.append(txns[j])
                        used[j] = True
            clusters.append(cluster)

        return clusters

    def _compute_average_days_between(
        self, dates: List[date]
    ) -> Optional[Decimal]:
        """Compute average number of days between consecutive dates."""
        if len(dates) < 2:
            return None
        sorted_dates = sorted(dates)
        gaps = [
            (sorted_dates[i + 1] - sorted_dates[i]).days
            for i in range(len(sorted_dates) - 1)
        ]
        if not gaps:
            return None
        return Decimal(str(sum(gaps) / len(gaps)))

    def _classify_frequency(
        self, avg_days: Optional[Decimal]
    ) -> str:
        """Map average days between occurrences to a frequency label.

        Thresholds (explicitly documented):
          - monthly    : 25 ≤ avg_days ≤ 35
          - bi-monthly : 50 ≤ avg_days ≤ 70
          - irregular  : anything else
        """
        if avg_days is None:
            return "irregular"
        if Decimal("25") <= avg_days <= Decimal("35"):
            return "monthly"
        if Decimal("50") <= avg_days <= Decimal("70"):
            return "bi-monthly"
        if Decimal("6") <= avg_days <= Decimal("9"):
            return "weekly"
        return "irregular"

    # ------------------------------------------------------------------
    # 7. Spending change detection
    # ------------------------------------------------------------------

    def detect_spending_changes(
        self,
        db: Session,
        user_id: uuid.UUID,
        current_start: date,
        current_end: date,
        previous_start: date,
        previous_end: date,
        currency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Compare category spending between two periods.

        For each (currency, category) found in either period:
        - absolute_change = current_amount - previous_amount
        - percentage_change = (absolute_change / previous_amount) * 100
          → None when previous_amount == 0

        direction: 'increased' | 'decreased' | 'unchanged'
        """
        current_breakdown = self.calculate_expense_breakdown(
            db, user_id, current_start, current_end, currency
        )
        previous_breakdown = self.calculate_expense_breakdown(
            db, user_id, previous_start, previous_end, currency
        )

        # Collect all (currency, category) pairs
        all_currencies: set[str] = set(current_breakdown.keys()) | set(
            previous_breakdown.keys()
        )

        changes: List[Dict[str, Any]] = []
        for cur in all_currencies:
            current_cats = {
                item["category"]: item["amount"]
                for item in current_breakdown.get(cur, [])
            }
            previous_cats = {
                item["category"]: item["amount"]
                for item in previous_breakdown.get(cur, [])
            }
            all_cats = set(current_cats.keys()) | set(previous_cats.keys())

            for cat in all_cats:
                curr_amt = current_cats.get(cat, Decimal("0"))
                prev_amt = previous_cats.get(cat, Decimal("0"))
                abs_change = _four_dp(curr_amt - prev_amt)

                pct_change: Optional[Decimal] = None
                if prev_amt > Decimal("0"):
                    pct_change = _two_dp(abs_change / prev_amt * Decimal("100"))

                if abs_change > Decimal("0"):
                    direction = "increased"
                elif abs_change < Decimal("0"):
                    direction = "decreased"
                else:
                    direction = "unchanged"

                changes.append(
                    {
                        "currency": cur,
                        "category": cat,
                        "previous_amount": _four_dp(prev_amt),
                        "current_amount": _four_dp(curr_amt),
                        "absolute_change": abs_change,
                        "percentage_change": pct_change,
                        "direction": direction,
                    }
                )

        # Sort: largest absolute change first
        changes.sort(key=lambda x: abs(x["absolute_change"]), reverse=True)
        return changes


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

financial_intelligence_service = FinancialIntelligenceService()
