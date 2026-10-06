"""Financial Scenario Simulation Service — Phase 11.

Provides deterministic, stateless mathematical scenario simulation over a
user's historical transaction data.

Engineering rules (same as Phase 10):
  - All monetary arithmetic uses Decimal (never float).
  - All queries are scoped by user_id (IDOR prevention).
  - Multi-currency data is NEVER aggregated across currencies.
  - No database writes — scenarios are pure read+compute.
  - No LLM, no ML, no financial advice is produced.
  - Real transaction/ledger/event data is never modified.

Phase 11 produces deterministic mathematical scenario projections.
It does NOT provide financial advice.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.schemas.scenario import (
    ScenarioFinancials,
    ScenarioImpact,
    ScenarioSimulateRequest,
    ScenarioSimulateResponse,
    ScenarioType,
)
from app.services.financial_intelligence import financial_intelligence_service

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Decimal helpers (consistent with Phase 10)
# ---------------------------------------------------------------------------

_TWO_DP = Decimal("0.01")
_FOUR_DP = Decimal("0.0001")


def _two_dp(value: Decimal) -> Decimal:
    """Round to 2 decimal places (ROUND_HALF_UP)."""
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _four_dp(value: Decimal) -> Decimal:
    """Round to 4 decimal places (ROUND_HALF_UP)."""
    return value.quantize(_FOUR_DP, rounding=ROUND_HALF_UP)


def _savings_rate(income: Decimal, net: Decimal) -> Optional[Decimal]:
    """Calculate savings rate (%). Returns None when income is zero."""
    if income == Decimal("0"):
        return None
    return _two_dp(net / income * Decimal("100"))


# ---------------------------------------------------------------------------
# Core scenario simulation service
# ---------------------------------------------------------------------------

class ScenarioSimulationService:
    """Stateless financial scenario simulation engine.

    Each method reads existing transaction data (via the Phase 10
    financial_intelligence_service), applies a deterministic mathematical
    transformation, and returns a structured result.

    No database writes are performed. No real financial data is modified.
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def simulate(
        self,
        db: Session,
        user_id: uuid.UUID,
        request: ScenarioSimulateRequest,
        period_start: date,
        period_end: date,
    ) -> ScenarioSimulateResponse:
        """Run a scenario simulation and return the structured result.

        Parameters
        ----------
        db:
            Database session (read-only — never written to).
        user_id:
            Authenticated user's ID. ALWAYS comes from the session,
            never from the request body.
        request:
            Validated scenario request.
        period_start / period_end:
            Resolved date range (the caller resolves period presets).

        Returns
        -------
        ScenarioSimulateResponse
            Baseline, scenario, and impact metrics. Never modifies data.
        """
        logger.info(
            "Scenario simulation: user=%s type=%s currency=%s period=%s→%s",
            user_id,
            request.scenario_type,
            request.currency,
            period_start,
            period_end,
        )

        # Step 1 — Retrieve baseline from Phase 10 intelligence service
        baseline = self._get_baseline(
            db=db,
            user_id=user_id,
            currency=request.currency,
            start_date=period_start,
            end_date=period_end,
        )

        # Step 2 — Apply the scenario transformation (pure math, no DB writes)
        scenario = self._apply_scenario(
            baseline=baseline,
            scenario_type=request.scenario_type,
            value=request.value,
        )

        # Step 3 — Compute impact
        impact = self._compute_impact(baseline=baseline, scenario=scenario)

        return ScenarioSimulateResponse(
            currency=request.currency,
            period_start=period_start,
            period_end=period_end,
            scenario_type=request.scenario_type,
            value=request.value,
            baseline=baseline,
            scenario=scenario,
            impact=impact,
        )

    # ------------------------------------------------------------------
    # Baseline retrieval
    # ------------------------------------------------------------------

    def _get_baseline(
        self,
        db: Session,
        user_id: uuid.UUID,
        currency: str,
        start_date: date,
        end_date: date,
    ) -> ScenarioFinancials:
        """Query the Phase 10 service for baseline income and expenses.

        Scoped strictly to user_id and currency — no cross-user or
        cross-currency data is ever returned.

        If there are no transactions for the requested currency in the
        requested period, returns a zero baseline (income=0, expenses=0).
        """
        flow = financial_intelligence_service.calculate_net_cash_flow(
            db=db,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )

        # If no transactions exist for this currency, return a zero baseline.
        cur_data = flow.get(currency.upper())
        if cur_data is None:
            income = Decimal("0")
            expenses = Decimal("0")
        else:
            income = _four_dp(Decimal(str(cur_data["total_income"])))
            expenses = _four_dp(Decimal(str(cur_data["total_expenses"])))

        net = _four_dp(income - expenses)
        sr = _savings_rate(income, net)

        return ScenarioFinancials(
            income=income,
            expenses=expenses,
            net_cash_flow=net,
            savings_rate=sr,
        )

    # ------------------------------------------------------------------
    # Scenario transformation (pure math — no DB access)
    # ------------------------------------------------------------------

    def _apply_scenario(
        self,
        baseline: ScenarioFinancials,
        scenario_type: ScenarioType,
        value: Decimal,
    ) -> ScenarioFinancials:
        """Apply the requested transformation to baseline metrics.

        All arithmetic uses Decimal. No database writes. No data modified.
        """
        income = baseline.income
        expenses = baseline.expenses

        if scenario_type == ScenarioType.EXPENSE_PERCENT_CHANGE:
            # expenses *= (1 + value/100)
            multiplier = Decimal("1") + value / Decimal("100")
            new_expenses = _four_dp(expenses * multiplier)
            new_income = income

        elif scenario_type == ScenarioType.INCOME_PERCENT_CHANGE:
            # income *= (1 + value/100)
            multiplier = Decimal("1") + value / Decimal("100")
            new_income = _four_dp(income * multiplier)
            new_expenses = expenses

        elif scenario_type == ScenarioType.ADD_MONTHLY_EXPENSE:
            # expenses += value
            new_expenses = _four_dp(expenses + value)
            new_income = income

        elif scenario_type == ScenarioType.REMOVE_MONTHLY_EXPENSE:
            # expenses -= value, floored at 0 (can't have negative expenses)
            reduced = expenses - value
            new_expenses = _four_dp(max(reduced, Decimal("0")))
            new_income = income

        elif scenario_type == ScenarioType.SAVINGS_TARGET:
            # Target savings amount is `value`.
            # Maximum allowable expenses = income - target_savings
            # (floored at 0)
            max_expenses = _four_dp(max(income - value, Decimal("0")))
            new_expenses = max_expenses
            new_income = income

        else:  # pragma: no cover — enum exhaustion guard
            raise ValueError(f"Unsupported scenario type: {scenario_type}")

        new_net = _four_dp(new_income - new_expenses)
        new_sr = _savings_rate(new_income, new_net)

        return ScenarioFinancials(
            income=new_income,
            expenses=new_expenses,
            net_cash_flow=new_net,
            savings_rate=new_sr,
        )

    # ------------------------------------------------------------------
    # Impact computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_impact(
        baseline: ScenarioFinancials,
        scenario: ScenarioFinancials,
    ) -> ScenarioImpact:
        """Compute the difference between scenario and baseline."""
        income_change = _four_dp(scenario.income - baseline.income)
        expense_change = _four_dp(scenario.expenses - baseline.expenses)
        net_change = _four_dp(scenario.net_cash_flow - baseline.net_cash_flow)

        sr_change: Optional[Decimal] = None
        if baseline.savings_rate is not None and scenario.savings_rate is not None:
            sr_change = _two_dp(scenario.savings_rate - baseline.savings_rate)

        return ScenarioImpact(
            income_change=income_change,
            expense_change=expense_change,
            net_cash_flow_change=net_change,
            savings_rate_change=sr_change,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

scenario_simulation_service = ScenarioSimulationService()
