"""Pydantic schemas for Phase 11: Financial Scenario Simulation Engine.

Scenario simulation is deterministic mathematical analysis based on
historical financial data. It is NOT financial advice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Scenario types
# ---------------------------------------------------------------------------

class ScenarioType(str, Enum):
    """Supported scenario simulation types.

    Each type applies a deterministic mathematical transformation to the user's
    baseline financial data for the requested period and currency.

    These calculations are NOT financial advice.
    """

    EXPENSE_PERCENT_CHANGE = "EXPENSE_PERCENT_CHANGE"
    """Apply a percentage change (positive = increase, negative = decrease) to
    baseline expenses. Value is a percentage, e.g. 10 means +10%."""

    INCOME_PERCENT_CHANGE = "INCOME_PERCENT_CHANGE"
    """Apply a percentage change (positive = increase, negative = decrease) to
    baseline income. Value is a percentage, e.g. -10 means -10%."""

    ADD_MONTHLY_EXPENSE = "ADD_MONTHLY_EXPENSE"
    """Add a flat monetary amount to baseline expenses.
    Value is the additional monthly expense in the selected currency."""

    REMOVE_MONTHLY_EXPENSE = "REMOVE_MONTHLY_EXPENSE"
    """Remove a flat monetary amount from baseline expenses.
    Value is the expense reduction in the selected currency."""

    SAVINGS_TARGET = "SAVINGS_TARGET"
    """Given a desired monthly savings amount (value), calculate the maximum
    allowable monthly expenses based on current income.
    The result shows what expenses must be capped at to hit the target."""


# ---------------------------------------------------------------------------
# Preset period names (mirrors Phase 10 _PERIOD_OPTIONS)
# ---------------------------------------------------------------------------

_VALID_PRESET_PERIODS = frozenset({
    "current_month",
    "previous_month",
    "last_30_days",
    "last_3_months",
    "last_6_months",
    "last_12_months",
})

# Maximum allowed percentage magnitude (prevent absurd inputs)
_MAX_PERCENT_MAGNITUDE = Decimal("10000")


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class ScenarioSimulateRequest(BaseModel):
    """Request body for POST /api/financial/scenarios/simulate.

    Exactly one of (period) or (start_date + end_date) must be provided,
    or the current_month default is used.
    Currency must be an ISO 4217 code (e.g. 'LKR', 'USD').

    Scenario simulation is deterministic mathematical analysis based on
    historical financial data. It is NOT financial advice.
    """

    scenario_type: ScenarioType = Field(
        ...,
        description=(
            "The type of scenario to simulate. One of: "
            "EXPENSE_PERCENT_CHANGE, INCOME_PERCENT_CHANGE, "
            "ADD_MONTHLY_EXPENSE, REMOVE_MONTHLY_EXPENSE, SAVINGS_TARGET."
        ),
    )

    value: Decimal = Field(
        ...,
        description=(
            "Numeric parameter for the scenario. "
            "For *_PERCENT_CHANGE: percentage points (e.g. 10 = +10%, -10 = -10%). "
            "For ADD_MONTHLY_EXPENSE / REMOVE_MONTHLY_EXPENSE: flat monetary amount (must be > 0). "
            "For SAVINGS_TARGET: desired monthly savings amount (must be >= 0)."
        ),
    )

    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description=(
            "ISO 4217 currency code (e.g. 'LKR', 'USD'). "
            "ONLY transactions in this currency are used. "
            "No cross-currency aggregation is ever performed."
        ),
    )

    # Period selection — mirrors Phase 10 approach
    period: Optional[str] = Field(
        None,
        description=(
            "Preset period alias. One of: "
            "current_month, previous_month, last_30_days, "
            "last_3_months, last_6_months, last_12_months. "
            "Ignored when start_date and end_date are both provided."
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
    def validate_request(self) -> "ScenarioSimulateRequest":
        """Cross-field validation."""
        # --- currency ---
        self.currency = self.currency.upper().strip()

        # --- period ---
        if self.period is not None:
            if self.period not in _VALID_PRESET_PERIODS:
                raise ValueError(
                    f"Invalid period '{self.period}'. "
                    f"Valid values: {', '.join(sorted(_VALID_PRESET_PERIODS))}."
                )

        # --- date range ---
        if self.start_date is not None or self.end_date is not None:
            if self.start_date is None or self.end_date is None:
                raise ValueError(
                    "Both start_date and end_date must be provided together."
                )
            if self.start_date > self.end_date:
                raise ValueError(
                    "start_date must not be after end_date."
                )

        # --- value validation by scenario type ---
        scenario_type = self.scenario_type
        value = self.value

        if scenario_type in (
            ScenarioType.EXPENSE_PERCENT_CHANGE,
            ScenarioType.INCOME_PERCENT_CHANGE,
        ):
            # Percentage: allow negative (decrease) or positive (increase)
            if abs(value) > _MAX_PERCENT_MAGNITUDE:
                raise ValueError(
                    f"Percentage value must be between "
                    f"-{_MAX_PERCENT_MAGNITUDE} and {_MAX_PERCENT_MAGNITUDE}."
                )
            if value < Decimal("-100"):
                raise ValueError(
                    "Percentage reduction cannot exceed -100% "
                    "(would result in negative baseline income/expenses)."
                )

        elif scenario_type in (
            ScenarioType.ADD_MONTHLY_EXPENSE,
            ScenarioType.REMOVE_MONTHLY_EXPENSE,
        ):
            # Flat monetary amount — must be strictly positive
            if value <= Decimal("0"):
                raise ValueError(
                    f"{scenario_type.value} requires a positive monetary value (got {value})."
                )

        elif scenario_type == ScenarioType.SAVINGS_TARGET:
            # Desired savings — must be non-negative
            if value < Decimal("0"):
                raise ValueError(
                    "SAVINGS_TARGET value (desired savings) must be >= 0."
                )

        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ScenarioFinancials(BaseModel):
    """A single set of financial metrics (baseline or scenario)."""

    income: Decimal = Field(description="Total income in the period for the selected currency.")
    expenses: Decimal = Field(description="Total expenses in the period for the selected currency.")
    net_cash_flow: Decimal = Field(description="income - expenses.")
    savings_rate: Optional[Decimal] = Field(
        None,
        description="(net_cash_flow / income) * 100. Null when income is zero.",
    )


class ScenarioImpact(BaseModel):
    """The calculated impact of the scenario vs. the baseline."""

    income_change: Decimal = Field(
        description="Scenario income minus baseline income."
    )
    expense_change: Decimal = Field(
        description="Scenario expenses minus baseline expenses."
    )
    net_cash_flow_change: Decimal = Field(
        description="Scenario net cash flow minus baseline net cash flow."
    )
    savings_rate_change: Optional[Decimal] = Field(
        None,
        description=(
            "Scenario savings rate minus baseline savings rate (percentage points). "
            "Null when either savings rate is null (income is zero)."
        ),
    )


class ScenarioSimulateResponse(BaseModel):
    """Response for POST /api/financial/scenarios/simulate.

    Scenario simulation is deterministic mathematical analysis based on
    historical financial data. It is NOT financial advice.
    """

    currency: str = Field(
        description="ISO 4217 currency used for this simulation."
    )
    period_start: date = Field(description="Start of the analysis period (inclusive).")
    period_end: date = Field(description="End of the analysis period (inclusive).")
    scenario_type: ScenarioType = Field(description="The scenario type that was simulated.")
    value: Decimal = Field(description="The input value used for this scenario.")

    baseline: ScenarioFinancials = Field(
        description="Actual financial metrics from historical transaction data."
    )
    scenario: ScenarioFinancials = Field(
        description="Projected financial metrics after applying the scenario."
    )
    impact: ScenarioImpact = Field(
        description="Difference between scenario and baseline."
    )

    disclaimer: str = Field(
        default=(
            "Scenario simulation is deterministic mathematical analysis based on "
            "historical financial data. It is not financial advice."
        ),
        description="Regulatory disclaimer.",
    )
