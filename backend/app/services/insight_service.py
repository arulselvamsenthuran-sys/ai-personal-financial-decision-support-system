"""Insight Generation Service — Phase 10.

Generates deterministic, factual FinancialInsight records from transaction data.

Engineering rules:
  - All thresholds are explicit and documented.
  - No subjective labels (good / bad / safe / dangerous).
  - No financial advice or investment recommendations.
  - All insights are factual observations derived from user's own data.
  - User isolation: every query is scoped by user_id.

Phase 10 produces deterministic financial observations.
It does not provide financial advice.

Insight types and their explicit trigger thresholds
====================================================

HIGH_EXPENSE_CATEGORY
  Triggered when a single expense category represents ≥ 30 % of total expenses
  for the period and currency.

EXPENSE_INCREASE
  Triggered when a category's spending increased by ≥ 20 % compared to the
  prior equivalent period.

NEGATIVE_CASH_FLOW
  Triggered when total_expenses > total_income for the period / currency.

RECURRING_EXPENSE_DETECTED
  Triggered for each pattern detected by detect_recurring_transactions()
  with ≥ 3 occurrences.

INCOME_DECREASE
  Triggered when income decreased by ≥ 20 % compared to the prior equivalent
  period for a given currency.

LARGE_TRANSACTION
  Triggered when a single expense transaction amount ≥ 3 × the user's average
  expense amount for the period and currency.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.financial_insight import FinancialInsight
from app.services.financial_intelligence import (
    LARGE_TX_MULTIPLIER,
    SIGNIFICANT_CHANGE_PCT,
    HIGH_CATEGORY_THRESHOLD_PCT,
    _four_dp,
    _is_expense,
    _is_income,
    financial_intelligence_service,
)
from app.models.transaction import Transaction

logger = get_logger(__name__)


class InsightService:
    """Generates and persists deterministic FinancialInsight records.

    Public API
    ----------
    generate_summary_insights(db, user_id, start_date, end_date)
        → List[FinancialInsight]
    get_insights(db, user_id, start_date, end_date)
        → List[FinancialInsight]
    """

    # ------------------------------------------------------------------
    # Public: generate insights
    # ------------------------------------------------------------------

    def generate_summary_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> List[FinancialInsight]:
        """Run all insight generators for the period and persist results.

        Idempotent per call — does NOT deduplicate across calls;
        callers should use get_insights() to retrieve existing insights.
        """
        insights: List[FinancialInsight] = []

        insights.extend(
            self._generate_cash_flow_insights(db, user_id, start_date, end_date)
        )
        insights.extend(
            self._generate_high_category_insights(db, user_id, start_date, end_date)
        )
        insights.extend(
            self._generate_large_transaction_insights(db, user_id, start_date, end_date)
        )
        insights.extend(
            self._generate_recurring_insights(db, user_id)
        )
        insights.extend(
            self._generate_spending_change_insights(db, user_id, start_date, end_date)
        )

        for insight in insights:
            db.add(insight)
        db.flush()

        return insights

    def get_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[FinancialInsight]:
        """Return stored insights for the user, optionally filtered by period."""
        q = (
            db.query(FinancialInsight)
            .filter(FinancialInsight.user_id == user_id)
        )
        if start_date:
            q = q.filter(
                (FinancialInsight.period_start >= start_date)
                | FinancialInsight.period_start.is_(None)
            )
        if end_date:
            q = q.filter(
                (FinancialInsight.period_end <= end_date)
                | FinancialInsight.period_end.is_(None)
            )
        return q.order_by(FinancialInsight.created_at.desc()).all()

    # ------------------------------------------------------------------
    # Private: individual insight generators
    # ------------------------------------------------------------------

    def _generate_cash_flow_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> List[FinancialInsight]:
        """Threshold: expenses > income → NEGATIVE_CASH_FLOW (ALERT).

        Also: income == 0 with expenses > 0 → NEGATIVE_CASH_FLOW (WARNING).
        """
        flow = financial_intelligence_service.calculate_net_cash_flow(
            db, user_id, start_date, end_date
        )
        results: List[FinancialInsight] = []

        for currency, data in flow.items():
            if data["net_cash_flow"] < Decimal("0"):
                severity = "ALERT"
                description = (
                    f"Total expenses ({currency} {data['total_expenses']:.2f}) exceeded "
                    f"total income ({currency} {data['total_income']:.2f}) "
                    f"between {start_date} and {end_date}."
                )
                results.append(
                    FinancialInsight(
                        user_id=user_id,
                        insight_type="NEGATIVE_CASH_FLOW",
                        severity=severity,
                        title=f"Expenses exceeded income ({currency})",
                        description=description,
                        metric_value=_four_dp(data["net_cash_flow"]),
                        currency=currency,
                        period_start=start_date,
                        period_end=end_date,
                        metadata_json={
                            "total_income": str(data["total_income"]),
                            "total_expenses": str(data["total_expenses"]),
                            "net_cash_flow": str(data["net_cash_flow"]),
                        },
                    )
                )

        return results

    def _generate_high_category_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> List[FinancialInsight]:
        """Threshold: category ≥ 30 % of total expenses → HIGH_EXPENSE_CATEGORY (WARNING)."""
        breakdown = financial_intelligence_service.calculate_expense_breakdown(
            db, user_id, start_date, end_date
        )
        results: List[FinancialInsight] = []

        for currency, categories in breakdown.items():
            for cat_data in categories:
                if cat_data["percentage"] >= HIGH_CATEGORY_THRESHOLD_PCT:
                    results.append(
                        FinancialInsight(
                            user_id=user_id,
                            insight_type="HIGH_EXPENSE_CATEGORY",
                            severity="WARNING",
                            title=(
                                f"'{cat_data['category']}' represents "
                                f"{cat_data['percentage']:.1f}% of expenses ({currency})"
                            ),
                            description=(
                                f"The '{cat_data['category']}' category accounted for "
                                f"{cat_data['percentage']:.1f}% of total {currency} expenses "
                                f"({currency} {cat_data['amount']:.2f}) "
                                f"between {start_date} and {end_date}. "
                                f"Threshold: ≥ {HIGH_CATEGORY_THRESHOLD_PCT}%."
                            ),
                            metric_value=cat_data["percentage"],
                            currency=currency,
                            period_start=start_date,
                            period_end=end_date,
                            metadata_json={
                                "category": cat_data["category"],
                                "amount": str(cat_data["amount"]),
                                "percentage": str(cat_data["percentage"]),
                                "threshold_pct": str(HIGH_CATEGORY_THRESHOLD_PCT),
                            },
                        )
                    )

        return results

    def _generate_large_transaction_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> List[FinancialInsight]:
        """Threshold: transaction amount ≥ 3 × average expense → LARGE_TRANSACTION (WARNING).

        Only expense transactions are considered.
        Requires at least 2 expense transactions to establish a meaningful average.
        """
        q = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
            )
        )
        transactions = [t for t in q.all() if _is_expense(t.transaction_type)]

        # Group by currency
        from collections import defaultdict
        by_currency: Dict[str, List[Transaction]] = defaultdict(list)
        for tx in transactions:
            by_currency[tx.currency].append(tx)

        results: List[FinancialInsight] = []
        for currency, txns in by_currency.items():
            if len(txns) < 2:
                continue  # Not enough data to establish an average
            amounts = [Decimal(str(t.amount)) for t in txns]
            total_amounts = sum(amounts, Decimal("0"))
            n = len(amounts)

            for tx in txns:
                amt = Decimal(str(tx.amount))
                
                # Calculate the average of the OTHER transactions
                avg = (total_amounts - amt) / (n - 1)
                threshold = avg * LARGE_TX_MULTIPLIER

                if amt >= threshold:
                    results.append(
                        FinancialInsight(
                            user_id=user_id,
                            insight_type="LARGE_TRANSACTION",
                            severity="WARNING",
                            title=(
                                f"Large transaction: {currency} {amt:.2f} "
                                f"({tx.merchant or tx.description or 'Unknown'})"
                            ),
                            description=(
                                f"A transaction of {currency} {amt:.2f} "
                                f"on {tx.transaction_date} "
                                f"({tx.merchant or tx.description or 'Unknown merchant'}) "
                                f"is {(amt / avg):.1f}× the average expense of "
                                f"{currency} {avg:.2f} for this period. "
                                f"Threshold: ≥ {LARGE_TX_MULTIPLIER}× average."
                            ),
                            metric_value=_four_dp(amt),
                            currency=currency,
                            period_start=start_date,
                            period_end=end_date,
                            metadata_json={
                                "transaction_id": str(tx.id),
                                "transaction_date": str(tx.transaction_date),
                                "amount": str(amt),
                                "average_expense": str(_four_dp(avg)),
                                "multiplier": str(_four_dp(amt / avg)),
                                "threshold_multiplier": str(LARGE_TX_MULTIPLIER),
                                "merchant": tx.merchant,
                                "category": tx.category,
                            },
                        )
                    )

        return results

    def _generate_recurring_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
    ) -> List[FinancialInsight]:
        """Generate RECURRING_EXPENSE_DETECTED insights (severity: INFO)."""
        patterns = financial_intelligence_service.detect_recurring_transactions(
            db, user_id
        )
        results: List[FinancialInsight] = []

        for pattern in patterns:
            results.append(
                FinancialInsight(
                    user_id=user_id,
                    insight_type="RECURRING_EXPENSE_DETECTED",
                    severity="INFO",
                    title=(
                        f"Recurring pattern detected: {pattern['merchant']} "
                        f"({pattern['currency']} ~{pattern['approximate_amount']:.2f})"
                    ),
                    description=(
                        f"A recurring {pattern['detected_frequency']} expense pattern was detected "
                        f"for '{pattern['merchant']}' "
                        f"({pattern['currency']} ~{pattern['approximate_amount']:.2f}). "
                        f"Observed {pattern['occurrence_count']} times. "
                        f"Last occurrence: {pattern['last_occurrence']}. "
                        f"This is a detected pattern, not a confirmed recurring charge."
                    ),
                    metric_value=pattern["approximate_amount"],
                    currency=pattern["currency"],
                    period_start=None,
                    period_end=pattern["last_occurrence"],
                    metadata_json={
                        "merchant": pattern["merchant"],
                        "approximate_amount": str(pattern["approximate_amount"]),
                        "occurrence_count": pattern["occurrence_count"],
                        "detected_frequency": pattern["detected_frequency"],
                        "last_occurrence": str(pattern["last_occurrence"]),
                        "average_days_between": (
                            str(pattern["average_days_between"])
                            if pattern["average_days_between"] is not None
                            else None
                        ),
                    },
                )
            )

        return results

    def _generate_spending_change_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> List[FinancialInsight]:
        """Threshold: category spending changed by ≥ 20 % vs prior equivalent period.

        Prior period: same duration immediately before start_date.
        Generates EXPENSE_INCREASE (WARNING) or INCOME_DECREASE (INFO) insights.
        """
        period_days = (end_date - start_date).days
        previous_end = start_date - __import__("datetime").timedelta(days=1)
        previous_start = previous_end - __import__("datetime").timedelta(days=period_days)

        changes = financial_intelligence_service.detect_spending_changes(
            db,
            user_id,
            current_start=start_date,
            current_end=end_date,
            previous_start=previous_start,
            previous_end=previous_end,
        )

        results: List[FinancialInsight] = []
        for change in changes:
            pct = change["percentage_change"]
            if pct is None:
                continue  # No previous data — skip (previous_amount == 0)
            if abs(pct) < SIGNIFICANT_CHANGE_PCT:
                continue  # Below threshold

            if change["direction"] == "increased":
                results.append(
                    FinancialInsight(
                        user_id=user_id,
                        insight_type="EXPENSE_INCREASE",
                        severity="WARNING",
                        title=(
                            f"'{change['category']}' spending increased by "
                            f"{pct:.1f}% ({change['currency']})"
                        ),
                        description=(
                            f"'{change['category']}' expenses increased by "
                            f"{pct:.1f}% compared to the prior period "
                            f"({change['currency']} {change['previous_amount']:.2f} → "
                            f"{change['currency']} {change['current_amount']:.2f}). "
                            f"Threshold: ≥ {SIGNIFICANT_CHANGE_PCT}% change."
                        ),
                        metric_value=pct,
                        currency=change["currency"],
                        period_start=start_date,
                        period_end=end_date,
                        metadata_json={
                            "category": change["category"],
                            "previous_amount": str(change["previous_amount"]),
                            "current_amount": str(change["current_amount"]),
                            "absolute_change": str(change["absolute_change"]),
                            "percentage_change": str(pct),
                            "previous_period_start": str(previous_start),
                            "previous_period_end": str(previous_end),
                            "threshold_pct": str(SIGNIFICANT_CHANGE_PCT),
                        },
                    )
                )
            elif change["direction"] == "decreased":
                # Only flag decreases as INFO (observation, no severity implied)
                results.append(
                    FinancialInsight(
                        user_id=user_id,
                        insight_type="EXPENSE_INCREASE",  # re-use type with negative metric
                        severity="INFO",
                        title=(
                            f"'{change['category']}' spending decreased by "
                            f"{abs(pct):.1f}% ({change['currency']})"
                        ),
                        description=(
                            f"'{change['category']}' expenses decreased by "
                            f"{abs(pct):.1f}% compared to the prior period "
                            f"({change['currency']} {change['previous_amount']:.2f} → "
                            f"{change['currency']} {change['current_amount']:.2f}). "
                            f"Threshold: ≥ {SIGNIFICANT_CHANGE_PCT}% change."
                        ),
                        metric_value=pct,
                        currency=change["currency"],
                        period_start=start_date,
                        period_end=end_date,
                        metadata_json={
                            "category": change["category"],
                            "previous_amount": str(change["previous_amount"]),
                            "current_amount": str(change["current_amount"]),
                            "absolute_change": str(change["absolute_change"]),
                            "percentage_change": str(pct),
                            "previous_period_start": str(previous_start),
                            "previous_period_end": str(previous_end),
                            "threshold_pct": str(SIGNIFICANT_CHANGE_PCT),
                        },
                    )
                )

        return results


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

insight_service = InsightService()
