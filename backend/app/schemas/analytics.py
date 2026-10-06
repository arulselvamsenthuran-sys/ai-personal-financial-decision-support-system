"""Pydantic schemas for Phase 10 Financial Intelligence & Analytics API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared / utility
# ---------------------------------------------------------------------------

class DateRangeInfo(BaseModel):
    """Describes the date range used for an analytics calculation."""

    period_start: date
    period_end: date


# ---------------------------------------------------------------------------
# Summary analytics
# ---------------------------------------------------------------------------

class AnalyticsSummaryByCurrency(BaseModel):
    """Income / expense summary for a single currency."""

    currency: str
    total_income: Decimal
    total_expenses: Decimal
    net_cash_flow: Decimal
    savings_rate: Optional[Decimal] = Field(
        None,
        description="(income - expenses) / income * 100. Null when income is zero.",
    )
    income_transaction_count: int
    expense_transaction_count: int
    transaction_count: int


class AnalyticsSummaryResponse(BaseModel):
    """Response for GET /api/financial/analytics/summary."""

    period_start: date
    period_end: date
    by_currency: List[AnalyticsSummaryByCurrency]


# ---------------------------------------------------------------------------
# Monthly cash flow
# ---------------------------------------------------------------------------

class MonthlyDataByCurrency(BaseModel):
    """One month's income / expense / net for a single currency."""

    year: int
    month: int
    currency: str
    income: Decimal
    expenses: Decimal
    net_cash_flow: Decimal
    income_transaction_count: int
    expense_transaction_count: int


class MonthlyAnalyticsResponse(BaseModel):
    """Response for GET /api/financial/analytics/monthly."""

    period_start: date
    period_end: date
    monthly_data: List[MonthlyDataByCurrency]


# ---------------------------------------------------------------------------
# Expense category breakdown
# ---------------------------------------------------------------------------

class CategoryBreakdownItem(BaseModel):
    """Expense amount and share for a single category within one currency."""

    currency: str
    category: str
    amount: Decimal
    transaction_count: int
    percentage: Decimal = Field(
        description="Percentage of total expenses in this currency (0–100)."
    )


class CategoryBreakdownResponse(BaseModel):
    """Response for GET /api/financial/analytics/categories."""

    period_start: date
    period_end: date
    categories: List[CategoryBreakdownItem]


# ---------------------------------------------------------------------------
# Recurring transaction detection
# ---------------------------------------------------------------------------

class RecurringTransactionItem(BaseModel):
    """A detected recurring transaction pattern.

    Note: This is a *detected pattern*, not a guarantee of recurrence.
    """

    currency: str
    merchant: str
    approximate_amount: Decimal
    occurrence_count: int
    detected_frequency: str = Field(
        description="Detected frequency pattern: 'monthly', 'bi-monthly', 'irregular'."
    )
    last_occurrence: date
    average_days_between: Optional[Decimal] = None


class RecurringTransactionsResponse(BaseModel):
    """Response for GET /api/financial/analytics/recurring."""

    detected_patterns: List[RecurringTransactionItem]
    note: str = Field(
        default=(
            "These are detected patterns based on transaction history. "
            "They are not confirmed recurring charges."
        )
    )


# ---------------------------------------------------------------------------
# Spending change detection
# ---------------------------------------------------------------------------

class SpendingChangeItem(BaseModel):
    """Spending change in one category between two periods."""

    currency: str
    category: str
    previous_amount: Decimal
    current_amount: Decimal
    absolute_change: Decimal
    percentage_change: Optional[Decimal] = Field(
        None,
        description="Null when previous_amount is zero (division not meaningful).",
    )
    direction: str = Field(description="'increased', 'decreased', or 'unchanged'.")


class SpendingChangesResponse(BaseModel):
    """Response for spending change comparison."""

    current_period_start: date
    current_period_end: date
    previous_period_start: date
    previous_period_end: date
    changes: List[SpendingChangeItem]


# ---------------------------------------------------------------------------
# Financial Insight
# ---------------------------------------------------------------------------

class FinancialInsightResponse(BaseModel):
    """Safe response schema for a FinancialInsight record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    insight_type: str
    severity: str
    title: str
    description: str
    metric_value: Optional[Decimal] = None
    currency: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime


class InsightsListResponse(BaseModel):
    """Response for GET /api/financial/insights."""

    period_start: Optional[date] = None
    period_end: Optional[date] = None
    insights: List[FinancialInsightResponse]
    total_count: int
