"""Financial Decision Support Engine — Phase 12.

Provides deterministic, explainable financial decision support evaluation over a
user's historical transaction and account state without providing financial advice
or executing autonomous financial actions.

Engineering rules:
  - All monetary arithmetic uses Decimal (never float).
  - All queries are scoped strictly by user_id (IDOR prevention).
  - Strict currency isolation: scenarios in currency X only evaluate against X.
  - No database writes: pure stateless read + compute.
  - Distinguishes one-time vs. recurring scenarios explicitly.
  - Clear data availability audit (transaction baseline, liquidity, simulation).
  - Safe denominators: never divides by zero or negative net cash flow.
  - Every metric/risk indicator includes source, rule, threshold, and explanation.
  - No LLM, no RAG, no embeddings, no investment recommendations.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.financial_account import FinancialAccount
from app.schemas.decision import (
    CashFlowProjection,
    ComponentAvailabilityStatus,
    DataAvailabilityAudit,
    DecisionAnalyzeRequest,
    DecisionAnalyzeResponse,
    DecisionScenarioType,
    EvidenceItem,
    LiquidityEvaluation,
    OverallDataAvailability,
    RatioMetric,
    RiskIndicator,
)
from app.services.financial_intelligence import (
    financial_intelligence_service,
)
from app.services.replay_service import replay_service

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Decimal Helpers
# ---------------------------------------------------------------------------

_TWO_DP = Decimal("0.01")
_FOUR_DP = Decimal("0.0001")


def _two_dp(value: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP."""
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _four_dp(value: Decimal) -> Decimal:
    """Round to 4 decimal places using ROUND_HALF_UP."""
    return value.quantize(_FOUR_DP, rounding=ROUND_HALF_UP)


def _savings_rate(income: Decimal, net: Decimal) -> Optional[Decimal]:
    """Calculate savings rate (%). Returns None when income <= 0."""
    if income <= Decimal("0"):
        return None
    return _two_dp(net / income * Decimal("100"))


# ---------------------------------------------------------------------------
# Centralized Deterministic Constants & Documented Heuristics
# ---------------------------------------------------------------------------

MIN_TRANSACTIONS_FOR_BASELINE: int = 3
"""Minimum transactions required in the currency to establish a baseline."""

MIN_MONTHS_FOR_BASELINE: int = 1
"""Minimum calendar span to establish a period baseline."""

HEURISTIC_LOW_SAVINGS_RATE_PCT: Decimal = Decimal("10.00")
"""Project-defined heuristic: flags when projected savings rate drops below 10.0%."""

HEURISTIC_HIGH_RECURRING_PRESSURE_PCT: Decimal = Decimal("25.00")
"""Project-defined heuristic: flags when a new recurring expense represents >= 25% of baseline monthly expenses."""

HEURISTIC_LARGE_PURCHASE_INCOME_RATIO: Decimal = Decimal("0.50")
"""Project-defined heuristic: flags when a one-time purchase exceeds 50% of monthly income."""


# ---------------------------------------------------------------------------
# Decision Support Engine Service
# ---------------------------------------------------------------------------

class DecisionSupportEngine:
    """Deterministic, explainable financial decision support service."""

    def analyze(
        self,
        db: Session,
        user_id: uuid.UUID,
        request: DecisionAnalyzeRequest,
        period_start: date,
        period_end: date,
    ) -> DecisionAnalyzeResponse:
        """Evaluate a hypothetical scenario against user's financial state."""
        currency = request.currency.upper()
        amount = _four_dp(request.amount)

        logger.info(
            "Decision support analysis: user=%s type=%s amount=%s %s period=%s->%s",
            user_id,
            request.scenario_type,
            amount,
            currency,
            period_start,
            period_end,
        )

        # 1. Fetch historical baseline from Phase 10
        baseline_flow = financial_intelligence_service.calculate_net_cash_flow(
            db=db,
            user_id=user_id,
            start_date=period_start,
            end_date=period_end,
            currency=currency,
        )
        cur_data = baseline_flow.get(currency)

        tx_count = cur_data["transaction_count"] if cur_data else 0
        baseline_income = _four_dp(Decimal(str(cur_data["total_income"]))) if cur_data else Decimal("0")
        baseline_expenses = _four_dp(Decimal(str(cur_data["total_expenses"]))) if cur_data else Decimal("0")
        baseline_net = _four_dp(baseline_income - baseline_expenses)
        baseline_sr = _savings_rate(baseline_income, baseline_net)

        # 2. Audit Liquidity & Account Balances
        liquidity_status, known_balance, balance_notes = self._audit_liquidity(
            db=db, user_id=user_id, currency=currency
        )

        # 3. Audit Data Availability
        data_audit, warnings = self._audit_data_availability(
            tx_count=tx_count,
            liquidity_status=liquidity_status,
            currency=currency,
            balance_notes=balance_notes,
            baseline_income=baseline_income,
            baseline_net=baseline_net,
        )

        # 4. Perform Scenario Transformation (distinguishing one-time vs recurring)
        cash_flow_projection = self._project_cash_flow(
            scenario_type=request.scenario_type,
            amount=amount,
            currency=currency,
            baseline_income=baseline_income,
            baseline_expenses=baseline_expenses,
            baseline_net=baseline_net,
            baseline_sr=baseline_sr,
        )

        # 5. Evaluate Liquidity Impact
        liquidity_evaluation = self._evaluate_liquidity(
            scenario_type=request.scenario_type,
            amount=amount,
            currency=currency,
            liquidity_status=liquidity_status,
            known_balance=known_balance,
        )

        # 6. Compute Safe Financial Ratios
        ratios = self._compute_safe_ratios(
            scenario_type=request.scenario_type,
            amount=amount,
            baseline_income=baseline_income,
            baseline_expenses=baseline_expenses,
            known_balance=known_balance,
        )

        # 7. Evaluate Deterministic Rules & Risk Indicators
        risk_indicators = self._evaluate_rules(
            request=request,
            amount=amount,
            currency=currency,
            baseline_income=baseline_income,
            baseline_expenses=baseline_expenses,
            baseline_net=baseline_net,
            projection=cash_flow_projection,
            liquidity_eval=liquidity_evaluation,
        )

        # 8. Compile Explainability Evidence
        evidence = self._compile_evidence(
            request=request,
            currency=currency,
            amount=amount,
            tx_count=tx_count,
            baseline_income=baseline_income,
            baseline_expenses=baseline_expenses,
            baseline_net=baseline_net,
            baseline_sr=baseline_sr,
            projection=cash_flow_projection,
            liquidity_eval=liquidity_evaluation,
            data_audit=data_audit,
        )

        return DecisionAnalyzeResponse(
            scenario_type=request.scenario_type,
            currency=currency,
            amount=_two_dp(amount),
            description=request.description,
            period_start=period_start,
            period_end=period_end,
            data_availability=data_audit,
            cash_flow_projection=cash_flow_projection,
            liquidity_evaluation=liquidity_evaluation,
            ratios=ratios,
            evidence=evidence,
            risk_indicators=risk_indicators,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Data Availability Auditing
    # ------------------------------------------------------------------

    def _audit_liquidity(
        self,
        db: Session,
        user_id: uuid.UUID,
        currency: str,
    ) -> tuple[ComponentAvailabilityStatus, Optional[Decimal], List[str]]:
        """Audit account state and derive verified liquid balance if authoritative."""
        notes: List[str] = []
        accounts = (
            db.query(FinancialAccount)
            .filter(
                FinancialAccount.user_id == user_id,
                FinancialAccount.currency == currency,
                FinancialAccount.is_active.is_(True),
            )
            .all()
        )

        if not accounts:
            notes.append(f"No active financial accounts found in {currency}.")
            return ComponentAvailabilityStatus.UNAVAILABLE, None, notes

        # Check if all accounts have established opening balances
        accounts_with_opening = [a for a in accounts if a.opening_balance is not None]
        if len(accounts_with_opening) < len(accounts):
            notes.append(
                f"{len(accounts) - len(accounts_with_opening)} of {len(accounts)} "
                f"{currency} accounts lack an opening balance; total liquidity is partial."
            )
            return ComponentAvailabilityStatus.PARTIAL, None, notes

        # Replay transactions for each account to calculate current balance
        total_balance = Decimal("0.0000")
        for acc in accounts:
            replay_res = replay_service.replay_account(
                db=db, user_id=user_id, financial_account_id=acc.id
            )
            acc_balance = Decimal(str(acc.opening_balance)) + replay_res["net_balance_movement"]
            total_balance += acc_balance

        return ComponentAvailabilityStatus.AVAILABLE, _four_dp(total_balance), notes

    def _audit_data_availability(
        self,
        tx_count: int,
        liquidity_status: ComponentAvailabilityStatus,
        currency: str,
        balance_notes: List[str],
        baseline_income: Decimal,
        baseline_net: Decimal,
    ) -> tuple[DataAvailabilityAudit, List[str]]:
        """Compute independent availability statuses across all dimensions."""
        notes: List[str] = list(balance_notes)
        warnings: List[str] = []

        # 1. Transaction baseline
        if tx_count == 0:
            tx_status = ComponentAvailabilityStatus.UNAVAILABLE
            notes.append(f"No historical transactions found in {currency} for the selected period.")
            warnings.append(f"Insufficient transaction data: 0 transactions found for {currency}.")
        elif tx_count < MIN_TRANSACTIONS_FOR_BASELINE:
            tx_status = ComponentAvailabilityStatus.PARTIAL
            notes.append(
                f"Only {tx_count} transaction(s) found in {currency} "
                f"(minimum {MIN_TRANSACTIONS_FOR_BASELINE} recommended for robust baseline)."
            )
            warnings.append(f"Limited historical data: Baseline is calculated from only {tx_count} transaction(s).")
        else:
            tx_status = ComponentAvailabilityStatus.AVAILABLE

        # 2. Simulation signals
        if tx_status == ComponentAvailabilityStatus.UNAVAILABLE:
            sim_status = ComponentAvailabilityStatus.UNAVAILABLE
        elif tx_status == ComponentAvailabilityStatus.PARTIAL:
            sim_status = ComponentAvailabilityStatus.PARTIAL
        else:
            sim_status = ComponentAvailabilityStatus.AVAILABLE

        # 3. Overall data availability
        if tx_status == ComponentAvailabilityStatus.UNAVAILABLE:
            overall = OverallDataAvailability.INSUFFICIENT
        elif tx_status == ComponentAvailabilityStatus.PARTIAL or liquidity_status != ComponentAvailabilityStatus.AVAILABLE:
            overall = OverallDataAvailability.PARTIAL
        else:
            overall = OverallDataAvailability.SUFFICIENT

        # Financial condition warnings
        if baseline_income == Decimal("0") and tx_count > 0:
            warnings.append(f"Baseline income for {currency} is zero in the selected period.")
        if baseline_net < Decimal("0"):
            warnings.append(f"Historical net cash flow is already negative ({currency} {baseline_net:.2f}).")
        if liquidity_status != ComponentAvailabilityStatus.AVAILABLE:
            warnings.append(f"Liquid account balance information is not fully available for {currency}.")

        audit = DataAvailabilityAudit(
            overall_status=overall,
            transaction_baseline=tx_status,
            liquidity_data=liquidity_status,
            simulation_signals=sim_status,
            transaction_count=tx_count,
            months_analyzed=MIN_MONTHS_FOR_BASELINE,
            notes=notes,
        )

        return audit, warnings

    # ------------------------------------------------------------------
    # Scenario Transformation
    # ------------------------------------------------------------------

    def _project_cash_flow(
        self,
        scenario_type: DecisionScenarioType,
        amount: Decimal,
        currency: str,
        baseline_income: Decimal,
        baseline_expenses: Decimal,
        baseline_net: Decimal,
        baseline_sr: Optional[Decimal],
    ) -> CashFlowProjection:
        """Apply mathematical scenario transformations."""
        if scenario_type == DecisionScenarioType.LARGE_PURCHASE:
            # ONE-TIME scenario:
            # - Monthly recurring income and expenses remain unchanged
            # - Period net cash flow is reduced by the one-off purchase amount
            proj_income = baseline_income
            proj_expenses = baseline_expenses
            proj_net = _four_dp(baseline_net - amount)
            proj_sr = _savings_rate(proj_income, proj_net)
            net_change = _four_dp(-amount)
            sr_change = _two_dp(proj_sr - baseline_sr) if (proj_sr is not None and baseline_sr is not None) else None
            summary = (
                f"One-time expenditure of {currency} {amount:.2f} reduces period net cash flow by {amount:.2f}. "
                f"Monthly recurring expense baseline remains unchanged at {currency} {baseline_expenses:.2f}."
            )
            is_one_time = True

        elif scenario_type == DecisionScenarioType.RECURRING_EXPENSE_ADD:
            # RECURRING scenario:
            # - Permanently increases monthly expenses
            proj_income = baseline_income
            proj_expenses = _four_dp(baseline_expenses + amount)
            proj_net = _four_dp(proj_income - proj_expenses)
            proj_sr = _savings_rate(proj_income, proj_net)
            net_change = _four_dp(-amount)
            sr_change = _two_dp(proj_sr - baseline_sr) if (proj_sr is not None and baseline_sr is not None) else None
            summary = (
                f"Adding a recurring monthly expense of {currency} {amount:.2f} increases monthly expenses to "
                f"{currency} {proj_expenses:.2f} and reduces recurring monthly net cash flow by {amount:.2f}."
            )
            is_one_time = False

        elif scenario_type == DecisionScenarioType.INCOME_REDUCTION:
            # RECURRING scenario:
            # - Permanently reduces monthly income (floored at zero)
            proj_income = _four_dp(max(baseline_income - amount, Decimal("0")))
            proj_expenses = baseline_expenses
            proj_net = _four_dp(proj_income - proj_expenses)
            proj_sr = _savings_rate(proj_income, proj_net)
            net_change = _four_dp(proj_income - baseline_income)
            sr_change = _two_dp(proj_sr - baseline_sr) if (proj_sr is not None and baseline_sr is not None) else None
            summary = (
                f"Recurring monthly income reduction of {currency} {amount:.2f} decreases monthly income to "
                f"{currency} {proj_income:.2f} and reduces recurring monthly net cash flow by {abs(net_change):.2f}."
            )
            is_one_time = False

        elif scenario_type == DecisionScenarioType.EXPENSE_INCREASE:
            # RECURRING scenario:
            # - Permanently expands monthly expenses
            proj_income = baseline_income
            proj_expenses = _four_dp(baseline_expenses + amount)
            proj_net = _four_dp(proj_income - proj_expenses)
            proj_sr = _savings_rate(proj_income, proj_net)
            net_change = _four_dp(-amount)
            sr_change = _two_dp(proj_sr - baseline_sr) if (proj_sr is not None and baseline_sr is not None) else None
            summary = (
                f"Recurring monthly expense expansion of {currency} {amount:.2f} increases monthly expenses to "
                f"{currency} {proj_expenses:.2f} and reduces recurring monthly net cash flow by {amount:.2f}."
            )
            is_one_time = False

        else:  # pragma: no cover
            raise ValueError(f"Unsupported scenario type: {scenario_type}")

        return CashFlowProjection(
            baseline_income=_two_dp(baseline_income),
            baseline_expenses=_two_dp(baseline_expenses),
            baseline_net_cash_flow=_two_dp(baseline_net),
            baseline_savings_rate=baseline_sr,
            projected_income=_two_dp(proj_income),
            projected_expenses=_two_dp(proj_expenses),
            projected_net_cash_flow=_two_dp(proj_net),
            projected_savings_rate=proj_sr,
            net_cash_flow_change=_two_dp(net_change),
            savings_rate_change=sr_change,
            is_one_time_impact=is_one_time,
            impact_summary=summary,
        )

    # ------------------------------------------------------------------
    # Liquidity Evaluation
    # ------------------------------------------------------------------

    def _evaluate_liquidity(
        self,
        scenario_type: DecisionScenarioType,
        amount: Decimal,
        currency: str,
        liquidity_status: ComponentAvailabilityStatus,
        known_balance: Optional[Decimal],
    ) -> LiquidityEvaluation:
        """Evaluate liquid coverage without making assumptions when data is missing."""
        if liquidity_status != ComponentAvailabilityStatus.AVAILABLE or known_balance is None:
            return LiquidityEvaluation(
                status=liquidity_status,
                known_liquid_balance=None,
                projected_balance_after=None,
                liquidity_coverage_ratio=None,
                is_liquid_balance_sufficient=None,
                explanation=(
                    f"Liquid account balance information is not fully verified for {currency}. "
                    "Liquidity impact cannot be computed."
                ),
            )

        projected_balance = _two_dp(known_balance - amount)
        coverage_ratio = _two_dp(known_balance / amount) if amount > Decimal("0") else None
        is_sufficient = known_balance >= amount

        if is_sufficient:
            explanation = (
                f"Known liquid balance ({currency} {known_balance:.2f}) covers the scenario amount "
                f"({currency} {amount:.2f}), leaving a projected balance of {currency} {projected_balance:.2f}."
            )
        else:
            explanation = (
                f"Known liquid balance ({currency} {known_balance:.2f}) is less than the scenario amount "
                f"({currency} {amount:.2f}) by {currency} {abs(projected_balance):.2f}."
            )

        return LiquidityEvaluation(
            status=ComponentAvailabilityStatus.AVAILABLE,
            known_liquid_balance=_two_dp(known_balance),
            projected_balance_after=projected_balance,
            liquidity_coverage_ratio=coverage_ratio,
            is_liquid_balance_sufficient=is_sufficient,
            explanation=explanation,
        )

    # ------------------------------------------------------------------
    # Safe Ratio Metrics
    # ------------------------------------------------------------------

    def _compute_safe_ratios(
        self,
        scenario_type: DecisionScenarioType,
        amount: Decimal,
        baseline_income: Decimal,
        baseline_expenses: Decimal,
        known_balance: Optional[Decimal],
    ) -> List[RatioMetric]:
        """Compute safe financial ratios only when denominators are strictly positive."""
        ratios: List[RatioMetric] = []

        # 1. Scenario Amount to Monthly Income Ratio
        if baseline_income > Decimal("0"):
            ratio_val = _two_dp(amount / baseline_income)
            ratios.append(
                RatioMetric(
                    name="scenario_amount_to_monthly_income",
                    value=ratio_val,
                    unit="ratio",
                    numerator=f"Scenario Amount ({amount:.2f})",
                    denominator=f"Baseline Monthly Income ({baseline_income:.2f})",
                    is_computable=True,
                    explanation=f"Scenario amount is {ratio_val:.2f}x of baseline monthly income.",
                )
            )
        else:
            ratios.append(
                RatioMetric(
                    name="scenario_amount_to_monthly_income",
                    value=None,
                    unit="ratio",
                    numerator=f"Scenario Amount ({amount:.2f})",
                    denominator="Baseline Monthly Income",
                    is_computable=False,
                    explanation="Baseline monthly income is zero or unavailable.",
                )
            )

        # 2. Scenario Amount to Known Liquid Balance Ratio
        if known_balance is not None and known_balance > Decimal("0"):
            ratio_val = _two_dp(amount / known_balance)
            ratios.append(
                RatioMetric(
                    name="scenario_amount_to_liquid_balance",
                    value=ratio_val,
                    unit="ratio",
                    numerator=f"Scenario Amount ({amount:.2f})",
                    denominator=f"Known Liquid Balance ({known_balance:.2f})",
                    is_computable=True,
                    explanation=f"Scenario amount represents {ratio_val * 100:.1f}% of known liquid balance.",
                )
            )
        else:
            ratios.append(
                RatioMetric(
                    name="scenario_amount_to_liquid_balance",
                    value=None,
                    unit="ratio",
                    numerator=f"Scenario Amount ({amount:.2f})",
                    denominator="Known Liquid Balance",
                    is_computable=False,
                    explanation="Known liquid balance is zero or unavailable.",
                )
            )

        # 3. Recurring Expense Pressure Ratio (for recurring scenarios)
        if scenario_type in (
            DecisionScenarioType.RECURRING_EXPENSE_ADD,
            DecisionScenarioType.EXPENSE_INCREASE,
        ):
            if baseline_expenses > Decimal("0"):
                ratio_val = _two_dp(amount / baseline_expenses * Decimal("100"))
                ratios.append(
                    RatioMetric(
                        name="recurring_expense_to_baseline_expenses",
                        value=ratio_val,
                        unit="percent",
                        numerator=f"New Recurring Expense ({amount:.2f})",
                        denominator=f"Baseline Expenses ({baseline_expenses:.2f})",
                        is_computable=True,
                        explanation=f"New expense adds {ratio_val:.1f}% on top of baseline monthly expenses.",
                    )
                )
            else:
                ratios.append(
                    RatioMetric(
                        name="recurring_expense_to_baseline_expenses",
                        value=None,
                        unit="percent",
                        numerator=f"New Recurring Expense ({amount:.2f})",
                        denominator="Baseline Expenses",
                        is_computable=False,
                        explanation="Baseline expenses are zero.",
                    )
                )

        return ratios

    # ------------------------------------------------------------------
    # Deterministic Rule Evaluator
    # ------------------------------------------------------------------

    def _evaluate_rules(
        self,
        request: DecisionAnalyzeRequest,
        amount: Decimal,
        currency: str,
        baseline_income: Decimal,
        baseline_expenses: Decimal,
        baseline_net: Decimal,
        projection: CashFlowProjection,
        liquidity_eval: LiquidityEvaluation,
    ) -> List[RiskIndicator]:
        """Evaluate explicit, deterministic rules against projected state."""
        indicators: List[RiskIndicator] = []

        # Rule 1: Deficit Net Cash Flow (Deterministic Accounting Rule)
        if projection.projected_net_cash_flow is not None and projection.projected_net_cash_flow < Decimal("0"):
            severity = "HIGH_RISK" if baseline_net >= Decimal("0") else "WARNING"
            indicators.append(
                RiskIndicator(
                    code="NEGATIVE_NET_CASH_FLOW",
                    severity=severity,
                    message=(
                        f"Projected net cash flow is negative ({currency} {projection.projected_net_cash_flow:.2f}). "
                        f"Projected expenses exceed projected income."
                    ),
                    deterministic_rule="projected_net_cash_flow < 0.00 (Accounting rule)",
                    trigger_value=f"{projection.projected_net_cash_flow:.2f}",
                    threshold_value="0.00",
                )
            )

        # Rule 2: Low Projected Savings Rate (Configurable Heuristic)
        if (
            projection.projected_savings_rate is not None
            and projection.projected_savings_rate < HEURISTIC_LOW_SAVINGS_RATE_PCT
        ):
            indicators.append(
                RiskIndicator(
                    code="LOW_SAVINGS_RATE",
                    severity="WARNING",
                    message=(
                        f"Projected savings rate ({projection.projected_savings_rate:.2f}%) is below the "
                        f"{HEURISTIC_LOW_SAVINGS_RATE_PCT}% reference threshold."
                    ),
                    deterministic_rule=(
                        f"projected_savings_rate < {HEURISTIC_LOW_SAVINGS_RATE_PCT}% (Configurable heuristic)"
                    ),
                    trigger_value=f"{projection.projected_savings_rate:.2f}%",
                    threshold_value=f"{HEURISTIC_LOW_SAVINGS_RATE_PCT}%",
                )
            )

        # Rule 3: High Recurring Expense Pressure (Configurable Heuristic)
        if request.scenario_type in (
            DecisionScenarioType.RECURRING_EXPENSE_ADD,
            DecisionScenarioType.EXPENSE_INCREASE,
        ):
            if baseline_expenses > Decimal("0"):
                pressure_pct = _two_dp(amount / baseline_expenses * Decimal("100"))
                if pressure_pct >= HEURISTIC_HIGH_RECURRING_PRESSURE_PCT:
                    indicators.append(
                        RiskIndicator(
                            code="HIGH_RECURRING_PRESSURE",
                            severity="WARNING",
                            message=(
                                f"New expense adds {pressure_pct:.1f}% to baseline monthly expenses, "
                                f"exceeding the {HEURISTIC_HIGH_RECURRING_PRESSURE_PCT}% reference threshold."
                            ),
                            deterministic_rule=(
                                f"new_expense / baseline_expenses >= {HEURISTIC_HIGH_RECURRING_PRESSURE_PCT}% (Configurable heuristic)"
                            ),
                            trigger_value=f"{pressure_pct:.2f}%",
                            threshold_value=f"{HEURISTIC_HIGH_RECURRING_PRESSURE_PCT}%",
                        )
                    )

        # Rule 4: Large Purchase Share of Monthly Income (Configurable Heuristic)
        if request.scenario_type == DecisionScenarioType.LARGE_PURCHASE:
            if baseline_income > Decimal("0"):
                share = _two_dp(amount / baseline_income)
                if share >= HEURISTIC_LARGE_PURCHASE_INCOME_RATIO:
                    indicators.append(
                        RiskIndicator(
                            code="LARGE_PURCHASE_HIGH_INCOME_SHARE",
                            severity="INFO",
                            message=(
                                f"One-time purchase represents {share * 100:.1f}% of baseline monthly income "
                                f"(reference threshold: {HEURISTIC_LARGE_PURCHASE_INCOME_RATIO * 100:.0f}%)."
                            ),
                            deterministic_rule=(
                                f"amount / monthly_income >= {HEURISTIC_LARGE_PURCHASE_INCOME_RATIO} (Configurable heuristic)"
                            ),
                            trigger_value=f"{share:.2f}",
                            threshold_value=f"{HEURISTIC_LARGE_PURCHASE_INCOME_RATIO:.2f}",
                        )
                    )

        # Rule 5: Insufficient Known Liquidity (Deterministic Liquidity Rule)
        if (
            liquidity_eval.status == ComponentAvailabilityStatus.AVAILABLE
            and liquidity_eval.is_liquid_balance_sufficient is False
            and liquidity_eval.known_liquid_balance is not None
        ):
            indicators.append(
                RiskIndicator(
                    code="INSUFFICIENT_LIQUIDITY",
                    severity="HIGH_RISK",
                    message=(
                        f"Scenario amount ({currency} {amount:.2f}) exceeds total verified liquid account "
                        f"balance ({currency} {liquidity_eval.known_liquid_balance:.2f})."
                    ),
                    deterministic_rule="amount > known_liquid_balance (Deterministic liquidity rule)",
                    trigger_value=f"{amount:.2f}",
                    threshold_value=f"{liquidity_eval.known_liquid_balance:.2f}",
                )
            )

        return indicators

    # ------------------------------------------------------------------
    # Explainability Evidence Compiler
    # ------------------------------------------------------------------

    def _compile_evidence(
        self,
        request: DecisionAnalyzeRequest,
        currency: str,
        amount: Decimal,
        tx_count: int,
        baseline_income: Decimal,
        baseline_expenses: Decimal,
        baseline_net: Decimal,
        baseline_sr: Optional[Decimal],
        projection: CashFlowProjection,
        liquidity_eval: LiquidityEvaluation,
        data_audit: DataAvailabilityAudit,
    ) -> List[EvidenceItem]:
        """Compile a complete, factual list of evidence records for explainability."""
        evidence: List[EvidenceItem] = [
            EvidenceItem(
                metric="baseline_transaction_count",
                value=str(tx_count),
                unit="count",
                rule="COUNT(transactions) for user, currency, and period",
                source="financial_intelligence",
                explanation=f"{tx_count} transaction(s) recorded in {currency} over the analysis window.",
            ),
            EvidenceItem(
                metric="baseline_income",
                value=f"{baseline_income:.2f}",
                unit=currency,
                rule="SUM(income transactions)",
                source="financial_intelligence",
                explanation=f"Baseline historical income for {currency}.",
            ),
            EvidenceItem(
                metric="baseline_expenses",
                value=f"{baseline_expenses:.2f}",
                unit=currency,
                rule="SUM(expense transactions)",
                source="financial_intelligence",
                explanation=f"Baseline historical expenses for {currency}.",
            ),
            EvidenceItem(
                metric="baseline_net_cash_flow",
                value=f"{baseline_net:.2f}",
                unit=currency,
                rule="baseline_income - baseline_expenses",
                source="financial_intelligence",
                explanation=f"Baseline net cash flow for {currency}.",
            ),
            EvidenceItem(
                metric="projected_net_cash_flow",
                value=f"{projection.projected_net_cash_flow:.2f}" if projection.projected_net_cash_flow is not None else "N/A",
                unit=currency,
                rule=(
                    "baseline_net - amount (one-time)"
                    if projection.is_one_time_impact
                    else "projected_income - projected_expenses (recurring)"
                ),
                source="decision_support_engine",
                explanation=projection.impact_summary,
            ),
            EvidenceItem(
                metric="liquidity_data_status",
                value=liquidity_eval.status.value,
                unit="status",
                rule="Verification of active financial accounts and opening balances",
                source="account_state",
                explanation=liquidity_eval.explanation,
            ),
        ]

        if baseline_sr is not None:
            evidence.append(
                EvidenceItem(
                    metric="baseline_savings_rate",
                    value=f"{baseline_sr:.2f}",
                    unit="percent",
                    rule="(baseline_net / baseline_income) * 100",
                    source="financial_intelligence",
                    explanation=f"Baseline historical savings rate is {baseline_sr:.2f}%.",
                )
            )

        if projection.projected_savings_rate is not None:
            evidence.append(
                EvidenceItem(
                    metric="projected_savings_rate",
                    value=f"{projection.projected_savings_rate:.2f}",
                    unit="percent",
                    rule="(projected_net / projected_income) * 100",
                    source="decision_support_engine",
                    explanation=f"Projected savings rate under scenario is {projection.projected_savings_rate:.2f}%.",
                )
            )

        return evidence


# Module-level singleton
decision_support_engine = DecisionSupportEngine()
