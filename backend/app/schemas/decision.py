"""Pydantic schemas for Phase 12: Financial Decision Support Engine.

Provides deterministic, explainable data contracts for scenario evaluation.
The engine does NOT provide financial or investment advice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DecisionScenarioType(str, Enum):
    """Supported scenario types for decision support evaluation."""

    LARGE_PURCHASE = "large_purchase"
    """One-time expenditure (e.g. equipment, vehicle, laptop).
    Affects period cash flow / liquidity; does NOT permanently modify recurring monthly expenses."""

    RECURRING_EXPENSE_ADD = "recurring_expense_add"
    """New ongoing monthly obligation (e.g. subscription, EMI, insurance).
    Modifies monthly recurring expenses, recurring net cash flow, and savings rate."""

    INCOME_REDUCTION = "income_reduction"
    """Ongoing decrease in monthly income (e.g. salary decrease, lost revenue stream).
    Modifies monthly recurring income, recurring net cash flow, and savings rate."""

    EXPENSE_INCREASE = "expense_increase"
    """Broad ongoing monthly expense expansion.
    Modifies monthly recurring expenses, recurring net cash flow, and savings rate."""


class ComponentAvailabilityStatus(str, Enum):
    """Availability status of individual analytical inputs."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class OverallDataAvailability(str, Enum):
    """Overall data adequacy for decision support evaluation."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


# Valid preset periods (mirrors Phase 10 / Phase 11)
_VALID_PRESET_PERIODS = frozenset({
    "current_month",
    "previous_month",
    "last_30_days",
    "last_3_months",
    "last_6_months",
    "last_12_months",
})


# ---------------------------------------------------------------------------
# Request Schema
# ---------------------------------------------------------------------------

class DecisionAnalyzeRequest(BaseModel):
    """Request model for POST /api/financial/decision-support/analyze."""

    scenario_type: DecisionScenarioType = Field(
        ...,
        description=(
            "Type of scenario to analyze: "
            "'large_purchase', 'recurring_expense_add', 'income_reduction', 'expense_increase'."
        ),
    )

    amount: Decimal = Field(
        ...,
        gt=Decimal("0"),
        description="Positive monetary amount in the specified currency.",
    )

    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code (e.g. 'LKR', 'USD'). Strict currency isolation is enforced.",
    )

    description: Optional[str] = Field(
        None,
        max_length=255,
        description="Optional human-readable description of the scenario (e.g., 'MacBook Pro purchase').",
    )

    period: Optional[str] = Field(
        "last_3_months",
        description=(
            "Preset period alias. One of: "
            "current_month, previous_month, last_30_days, "
            "last_3_months, last_6_months, last_12_months. "
            "Ignored if start_date and end_date are both provided."
        ),
    )

    start_date: Optional[date] = Field(
        None,
        description="Custom period start date (inclusive). Must be <= end_date.",
    )

    end_date: Optional[date] = Field(
        None,
        description="Custom period end date (inclusive). Must be >= start_date.",
    )

    @model_validator(mode="after")
    def validate_request(self) -> "DecisionAnalyzeRequest":
        """Cross-field validation."""
        self.currency = self.currency.upper().strip()
        if not self.currency.isalpha():
            raise ValueError(f"Currency code '{self.currency}' must contain only alphabetic characters.")

        if self.period is not None:
            if self.period not in _VALID_PRESET_PERIODS:
                raise ValueError(
                    f"Invalid period '{self.period}'. "
                    f"Valid values: {', '.join(sorted(_VALID_PRESET_PERIODS))}."
                )

        if self.start_date is not None or self.end_date is not None:
            if self.start_date is None or self.end_date is None:
                raise ValueError("Both start_date and end_date must be provided together.")
            if self.start_date > self.end_date:
                raise ValueError("start_date must not be after end_date.")

        return self


# ---------------------------------------------------------------------------
# Response Components
# ---------------------------------------------------------------------------

class DataAvailabilityAudit(BaseModel):
    """Detailed audit of data sufficiency across all dimensions."""

    overall_status: OverallDataAvailability = Field(
        description="Overall evaluation status: sufficient, partial, or insufficient."
    )
    transaction_baseline: ComponentAvailabilityStatus = Field(
        description="Availability of historical transaction data in the requested currency."
    )
    liquidity_data: ComponentAvailabilityStatus = Field(
        description="Availability of authoritative liquid account balance data in the requested currency."
    )
    simulation_signals: ComponentAvailabilityStatus = Field(
        description="Availability of mathematical scenario projection signals."
    )
    transaction_count: int = Field(
        description="Number of transactions found for this user in the requested currency during the period."
    )
    months_analyzed: int = Field(
        description="Approximate number of calendar months in the analysis window."
    )
    notes: List[str] = Field(
        default_factory=list,
        description="Auditing notes explaining any partial or missing data dimensions.",
    )


class EvidenceItem(BaseModel):
    """Explainable factual evidence record."""

    metric: str = Field(description="Name of the computed metric.")
    value: str = Field(description="Formatted string representation of the metric value.")
    unit: str = Field(description="Unit of measurement (e.g. 'currency_amount', 'percent', 'ratio', 'count').")
    rule: str = Field(description="Underlying deterministic rule or formula.")
    source: str = Field(description="Source subsystem (e.g. 'financial_intelligence', 'scenario_simulation', 'account_state').")
    explanation: str = Field(description="Human-readable factual explanation of how this was derived.")


class RiskIndicator(BaseModel):
    """Deterministic risk or condition flag triggered by explicit rules."""

    code: str = Field(description="Machine-readable rule/risk code.")
    severity: str = Field(description="Severity level: 'INFO', 'WARNING', or 'HIGH_RISK'.")
    message: str = Field(description="Factual description of the condition.")
    deterministic_rule: str = Field(description="Explicit deterministic logic or heuristic definition.")
    trigger_value: str = Field(description="Actual evaluated value.")
    threshold_value: str = Field(description="Threshold value that caused the trigger.")


class CashFlowProjection(BaseModel):
    """Historical baseline vs. scenario projected cash flow."""

    baseline_income: Optional[Decimal] = Field(
        None, description="Average or total baseline income in the period."
    )
    baseline_expenses: Optional[Decimal] = Field(
        None, description="Average or total baseline expenses in the period."
    )
    baseline_net_cash_flow: Optional[Decimal] = Field(
        None, description="baseline_income - baseline_expenses."
    )
    baseline_savings_rate: Optional[Decimal] = Field(
        None, description="(baseline_net_cash_flow / baseline_income) * 100. Null when income is 0."
    )
    projected_income: Optional[Decimal] = Field(
        None, description="Projected income under scenario."
    )
    projected_expenses: Optional[Decimal] = Field(
        None, description="Projected expenses under scenario."
    )
    projected_net_cash_flow: Optional[Decimal] = Field(
        None, description="Projected net cash flow under scenario."
    )
    projected_savings_rate: Optional[Decimal] = Field(
        None, description="Projected savings rate under scenario. Null when income is 0."
    )
    net_cash_flow_change: Optional[Decimal] = Field(
        None, description="projected_net_cash_flow - baseline_net_cash_flow."
    )
    savings_rate_change: Optional[Decimal] = Field(
        None, description="projected_savings_rate - baseline_savings_rate (percentage points)."
    )
    is_one_time_impact: bool = Field(
        description="True for one-time events (large_purchase); False for permanent recurring modifications."
    )
    impact_summary: str = Field(
        description="Factual summary of cash flow movement."
    )


class LiquidityEvaluation(BaseModel):
    """Evaluation of available liquid balances and coverage."""

    status: ComponentAvailabilityStatus = Field(
        description="Liquidity data availability status: 'available', 'partial', or 'unavailable'."
    )
    known_liquid_balance: Optional[Decimal] = Field(
        None, description="Total verified liquid account balance in requested currency, if fully available."
    )
    projected_balance_after: Optional[Decimal] = Field(
        None, description="known_liquid_balance - purchase amount. Null if balance is unavailable."
    )
    liquidity_coverage_ratio: Optional[Decimal] = Field(
        None, description="known_liquid_balance / purchase amount. Null if balance is unavailable or amount is 0."
    )
    is_liquid_balance_sufficient: Optional[bool] = Field(
        None, description="True if known_liquid_balance >= amount; False if less; Null if liquidity data is unavailable."
    )
    explanation: str = Field(
        description="Detailed explanation of liquidity availability and outcome."
    )


class RatioMetric(BaseModel):
    """Safely computed financial ratio."""

    name: str = Field(description="Identifier of the ratio metric.")
    value: Optional[Decimal] = Field(
        None, description="Computed decimal value, or null if denominator is not strictly positive / unavailable."
    )
    unit: str = Field(description="Unit of representation (e.g. 'ratio', 'percent').")
    numerator: str = Field(description="Description/source of the numerator.")
    denominator: str = Field(description="Description/source of the denominator.")
    is_computable: bool = Field(
        description="True if denominator is positive and valid; False otherwise."
    )
    explanation: str = Field(
        description="Factual interpretation or reason why the ratio could not be computed."
    )


class DecisionAnalyzeResponse(BaseModel):
    """Complete structured response for decision support analysis."""

    scenario_type: DecisionScenarioType = Field(description="Type of scenario evaluated.")
    currency: str = Field(description="ISO 4217 currency code used.")
    amount: Decimal = Field(description="Scenario monetary amount evaluated.")
    description: Optional[str] = Field(None, description="Scenario description if provided.")
    period_start: date = Field(description="Start date of the historical analysis window.")
    period_end: date = Field(description="End date of the historical analysis window.")

    data_availability: DataAvailabilityAudit = Field(
        description="Audit of data sufficiency across all dimensions."
    )
    cash_flow_projection: CashFlowProjection = Field(
        description="Baseline vs. projected cash flow metrics."
    )
    liquidity_evaluation: LiquidityEvaluation = Field(
        description="Liquidity and balance evaluation."
    )
    ratios: List[RatioMetric] = Field(
        default_factory=list, description="Safely computed financial ratio metrics."
    )
    evidence: List[EvidenceItem] = Field(
        default_factory=list, description="Structured explainability evidence list."
    )
    risk_indicators: List[RiskIndicator] = Field(
        default_factory=list, description="Deterministic risk indicators and rule triggers."
    )
    warnings: List[str] = Field(
        default_factory=list, description="Data availability and boundary warnings."
    )
    disclaimer: str = Field(
        default=(
            "This decision support analysis is a deterministic mathematical evaluation based on "
            "historical financial data. It does not provide personalized investment, legal, or financial advice. "
            "The final decision always remains with the user."
        ),
        description="Standard regulatory disclaimer.",
    )
