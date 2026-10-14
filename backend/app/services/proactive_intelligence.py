"""Proactive Intelligence Engine Service — Phase 18.

Detects meaningful financial changes, patterns, risks, and opportunities from user's
verified transaction data without requiring a prompt or question.

Engineering Rules:
  - Strict Source of Truth: Deterministic calculations only. No LLM financial logic.
  - Read-Only & User Isolated: All queries filter by authenticated user_id (IDOR prevention).
  - Currency Isolation: Multi-currency data evaluated independently per currency.
  - Data Sufficiency Enforcement: Suppresses false alarms when transaction data is insufficient.
  - Structured Evidence: Every insight contains complete numeric evidence allowing verification.
  - Safe AI Explanation: LLM translates verified evidence into natural language; never invents metrics.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.ai_safety import (
    detect_prompt_injection,
    sanitize_untrusted_content,
)
from app.core.logging import get_logger
from app.models.transaction import Transaction
from app.schemas.proactive_intelligence import (
    InsightEvidence,
    ProactiveExplainRequest,
    ProactiveExplainResponse,
    ProactiveInsight,
    ProactiveInsightsResponse,
)
from app.services.financial_intelligence import (
    _CREDIT_TYPES,
    _DEBIT_TYPES,
    financial_intelligence_service,
)
from app.services.llm.provider import LLMProviderError, get_llm_provider
from app.services.llm.service import ai_explanation_service

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Deterministic Threshold Constants (Centralized)
# ---------------------------------------------------------------------------

# Minimum total transactions required for proactive baseline analysis
MIN_TRANSACTIONS_REQUIRED: int = 5

# Minimum transaction span in days required for baseline comparison
MIN_DAYS_REQUIRED: int = 30

# Percentage thresholds for significant change
SPENDING_CHANGE_THRESHOLD_PCT: Decimal = Decimal("15.0")
INCOME_CHANGE_THRESHOLD_PCT: Decimal = Decimal("15.0")
SAVINGS_RATE_CHANGE_THRESHOLD_PCT: Decimal = Decimal("5.0")  # percentage points
RECURRING_INCREASE_THRESHOLD_PCT: Decimal = Decimal("10.0")

# Liquidity buffer runway threshold (months)
LIQUIDITY_BUFFER_LOW_MONTHS: Decimal = Decimal("2.0")
LIQUIDITY_BUFFER_CRITICAL_MONTHS: Decimal = Decimal("1.0")


def _two_dp(val: Optional[Decimal]) -> Decimal:
    """Format Decimal to 2 decimal places."""
    if val is None:
        return Decimal("0.00")
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class ProactiveIntelligenceService:
    """Service for deterministic proactive insight generation and AI explanation."""

    def __init__(self, llm_provider=None):
        self._llm_provider = llm_provider

    def _get_provider(self):
        return self._llm_provider or get_llm_provider()

    # -----------------------------------------------------------------------
    # Core Proactive Analysis
    # -----------------------------------------------------------------------

    def generate_proactive_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
    ) -> ProactiveInsightsResponse:
        """Analyze user's transaction data and generate proactive insights.

        Enforces user ownership, currency isolation, and data sufficiency rules.
        """
        # 1. Check overall data sufficiency
        total_tx_count = (
            db.query(func.count(Transaction.id))
            .filter(Transaction.user_id == user_id)
            .scalar()
            or 0
        )

        if total_tx_count < MIN_TRANSACTIONS_REQUIRED:
            return ProactiveInsightsResponse(
                total_count=0,
                data_sufficient=False,
                data_sufficiency_reason=(
                    f"Insufficient transaction history. At least {MIN_TRANSACTIONS_REQUIRED} transactions "
                    f"are required to calculate a reliable baseline (found {total_tx_count})."
                ),
                currencies_evaluated=[],
                insights=[],
            )

        # 2. Find distinct currencies
        currencies = [
            row[0]
            for row in db.query(Transaction.currency)
            .filter(Transaction.user_id == user_id)
            .distinct()
            .all()
            if row[0]
        ]

        if not currencies:
            return ProactiveInsightsResponse(
                total_count=0,
                data_sufficient=False,
                data_sufficiency_reason="No financial transactions with valid currency codes found.",
                currencies_evaluated=[],
                insights=[],
            )

        # 3. Evaluate proactive insights per currency
        all_insights: List[ProactiveInsight] = []
        currencies_evaluated: List[str] = []

        for currency in currencies:
            curr_insights = self._evaluate_currency_insights(
                db=db, user_id=user_id, currency=currency
            )
            if curr_insights is not None:
                all_insights.extend(curr_insights)
                currencies_evaluated.append(currency)

        return ProactiveInsightsResponse(
            total_count=len(all_insights),
            data_sufficient=True,
            data_sufficiency_reason=None,
            currencies_evaluated=currencies_evaluated,
            insights=all_insights,
        )

    def _evaluate_currency_insights(
        self,
        db: Session,
        user_id: uuid.UUID,
        currency: str,
    ) -> Optional[List[ProactiveInsight]]:
        """Evaluate proactive insights for a specific currency."""
        # Retrieve recent 30-day metrics
        start_30 = date.today() - timedelta(days=30)
        end_30 = date.today()

        cf_30 = financial_intelligence_service.calculate_net_cash_flow(
            db=db,
            user_id=user_id,
            start_date=start_30,
            end_date=end_30,
            currency=currency,
        )

        curr_summary = cf_30.get(currency)
        if not curr_summary or curr_summary["transaction_count"] < 2:
            return None

        # Retrieve historical baseline (60 days prior to recent 30-day period)
        start_base = date.today() - timedelta(days=90)
        end_base = date.today() - timedelta(days=30)

        cf_base = financial_intelligence_service.calculate_net_cash_flow(
            db=db,
            user_id=user_id,
            start_date=start_base,
            end_date=end_base,
            currency=currency,
        )

        base_summary = cf_base.get(currency)
        if not base_summary or base_summary["transaction_count"] < 2:
            return None

        # Calculate monthly average for baseline period (2 months)
        months_in_base = Decimal("2.0")
        base_inc = Decimal(str(base_summary["total_income"])) / months_in_base
        base_exp = Decimal(str(base_summary["total_expenses"])) / months_in_base
        base_net = Decimal(str(base_summary["net_cash_flow"])) / months_in_base
        base_sr = Decimal(str(base_summary["savings_rate"])) if base_summary["savings_rate"] is not None else None

        insights: List[ProactiveInsight] = []

        curr_inc = Decimal(str(curr_summary["total_income"]))
        curr_exp = Decimal(str(curr_summary["total_expenses"]))
        curr_net = Decimal(str(curr_summary["net_cash_flow"]))
        curr_sr = Decimal(str(curr_summary["savings_rate"])) if curr_summary["savings_rate"] is not None else None

        # Data confidence based on baseline transaction count
        if base_summary["transaction_count"] >= 6:
            confidence = "HIGH"
        elif base_summary["transaction_count"] >= 3:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        # -------------------------------------------------------------------
        # Rule 1: SPENDING_INCREASE / SPENDING_DECREASE
        # -------------------------------------------------------------------
        if base_exp > Decimal("0.00"):
            exp_change_pct = ((curr_exp - base_exp) / base_exp) * Decimal("100.00")
            if exp_change_pct >= SPENDING_CHANGE_THRESHOLD_PCT:
                severity = "HIGH" if exp_change_pct >= Decimal("40.0") else ("MEDIUM" if exp_change_pct >= Decimal("25.0") else "LOW")
                insights.append(
                    self._build_insight(
                        user_id=user_id,
                        currency=currency,
                        insight_type="SPENDING_INCREASE",
                        severity=severity,
                        title=f"Recent spending is {_two_dp(exp_change_pct)}% higher than 3-month baseline",
                        description=(
                            f"Your expenses over the last 30 days ({currency} {_two_dp(curr_exp)}) "
                            f"exceeded your historical 3-month average ({currency} {_two_dp(base_exp)}) "
                            f"by {_two_dp(curr_exp - base_exp)} ({_two_dp(exp_change_pct)}%)."
                        ),
                        metric="monthly_expenses",
                        current_value=curr_exp,
                        baseline_value=base_exp,
                        change_amount=curr_exp - base_exp,
                        change_percent=_two_dp(exp_change_pct),
                        period_label="Last 30 Days vs 3-Month Baseline",
                        confidence=confidence,
                    )
                )
            elif exp_change_pct <= -SPENDING_CHANGE_THRESHOLD_PCT:
                insights.append(
                    self._build_insight(
                        user_id=user_id,
                        currency=currency,
                        insight_type="SPENDING_DECREASE",
                        severity="INFO",
                        title=f"Recent spending is {_two_dp(abs(exp_change_pct))}% lower than 3-month baseline",
                        description=(
                            f"Your expenses over the last 30 days ({currency} {_two_dp(curr_exp)}) "
                            f"were lower than your 3-month average ({currency} {_two_dp(base_exp)}) "
                            f"by {_two_dp(base_exp - curr_exp)}."
                        ),
                        metric="monthly_expenses",
                        current_value=curr_exp,
                        baseline_value=base_exp,
                        change_amount=curr_exp - base_exp,
                        change_percent=_two_dp(exp_change_pct),
                        period_label="Last 30 Days vs 3-Month Baseline",
                        confidence=confidence,
                    )
                )

        # -------------------------------------------------------------------
        # Rule 2: SAVINGS_RATE_DECLINE / SAVINGS_RATE_IMPROVEMENT
        # -------------------------------------------------------------------
        if curr_sr is not None and base_sr is not None:
            sr_diff = curr_sr - base_sr  # percentage points difference
            if sr_diff <= -SAVINGS_RATE_CHANGE_THRESHOLD_PCT:
                severity = "HIGH" if sr_diff <= Decimal("-15.0") else "MEDIUM"
                insights.append(
                    self._build_insight(
                        user_id=user_id,
                        currency=currency,
                        insight_type="SAVINGS_RATE_DECLINE",
                        severity=severity,
                        title=f"Savings rate declined by {_two_dp(abs(sr_diff))} percentage points",
                        description=(
                            f"Your savings rate in the last 30 days ({_two_dp(curr_sr)}%) "
                            f"dropped compared to your 3-month baseline ({_two_dp(base_sr)}%)."
                        ),
                        metric="savings_rate",
                        current_value=_two_dp(curr_sr),
                        baseline_value=_two_dp(base_sr),
                        change_amount=_two_dp(sr_diff),
                        change_percent=None,
                        period_label="Last 30 Days vs 3-Month Baseline",
                        confidence=confidence,
                    )
                )
            elif sr_diff >= SAVINGS_RATE_CHANGE_THRESHOLD_PCT:
                insights.append(
                    self._build_insight(
                        user_id=user_id,
                        currency=currency,
                        insight_type="SAVINGS_RATE_IMPROVEMENT",
                        severity="INFO",
                        title=f"Savings rate improved by {_two_dp(sr_diff)} percentage points",
                        description=(
                            f"Your recent savings rate ({_two_dp(curr_sr)}%) "
                            f"increased compared to your 3-month baseline ({_two_dp(base_sr)}%)."
                        ),
                        metric="savings_rate",
                        current_value=_two_dp(curr_sr),
                        baseline_value=_two_dp(base_sr),
                        change_amount=_two_dp(sr_diff),
                        change_percent=None,
                        period_label="Last 30 Days vs 3-Month Baseline",
                        confidence=confidence,
                    )
                )

        # -------------------------------------------------------------------
        # Rule 3: CASH_FLOW_DETERIORATION / CASH_FLOW_IMPROVEMENT
        # -------------------------------------------------------------------
        if curr_net < Decimal("0.00") and base_net >= Decimal("0.00"):
            insights.append(
                self._build_insight(
                    user_id=user_id,
                    currency=currency,
                    insight_type="CASH_FLOW_DETERIORATION",
                    severity="HIGH",
                    title="Net cash flow turned negative over the last 30 days",
                    description=(
                        f"Your net cash flow was negative ({currency} {_two_dp(curr_net)}) "
                        f"over the recent period, reversing a positive historical average "
                        f"({currency} {_two_dp(base_net)})."
                    ),
                    metric="net_cash_flow",
                    current_value=curr_net,
                    baseline_value=base_net,
                    change_amount=curr_net - base_net,
                    change_percent=None,
                    period_label="Last 30 Days vs 3-Month Baseline",
                    confidence=confidence,
                )
            )
        elif curr_net > base_net + Decimal("10000.00") and base_net > Decimal("0.00"):
            insights.append(
                self._build_insight(
                    user_id=user_id,
                    currency=currency,
                    insight_type="CASH_FLOW_IMPROVEMENT",
                    severity="INFO",
                    title="Net cash flow improved over recent baseline",
                    description=(
                        f"Your net cash flow of {currency} {_two_dp(curr_net)} "
                        f"exceeded your historical monthly average ({currency} {_two_dp(base_net)})."
                    ),
                    metric="net_cash_flow",
                    current_value=curr_net,
                    baseline_value=base_net,
                    change_amount=curr_net - base_net,
                    change_percent=None,
                    period_label="Last 30 Days vs 3-Month Baseline",
                    confidence=confidence,
                )
            )

        # -------------------------------------------------------------------
        # Rule 4: INCOME_CHANGE
        # -------------------------------------------------------------------
        if base_inc > Decimal("0.00"):
            inc_change_pct = ((curr_inc - base_inc) / base_inc) * Decimal("100.00")
            if inc_change_pct <= -INCOME_CHANGE_THRESHOLD_PCT:
                severity = "HIGH" if inc_change_pct <= Decimal("-30.0") else "MEDIUM"
                insights.append(
                    self._build_insight(
                        user_id=user_id,
                        currency=currency,
                        insight_type="INCOME_CHANGE",
                        severity=severity,
                        title=f"Recent income is {_two_dp(abs(inc_change_pct))}% lower than baseline",
                        description=(
                            f"Your monthly income over the last 30 days ({currency} {_two_dp(curr_inc)}) "
                            f"was lower than your 3-month baseline average ({currency} {_two_dp(base_inc)})."
                        ),
                        metric="monthly_income",
                        current_value=curr_inc,
                        baseline_value=base_inc,
                        change_amount=curr_inc - base_inc,
                        change_percent=_two_dp(inc_change_pct),
                        period_label="Last 30 Days vs 3-Month Baseline",
                        confidence=confidence,
                    )
                )

        # -------------------------------------------------------------------
        # Rule 5: RECURRING_EXPENSE_INCREASE
        # -------------------------------------------------------------------
        recurring_patterns = financial_intelligence_service.detect_recurring_transactions(
            db=db,
            user_id=user_id,
            currency=currency,
        )

        for pat in recurring_patterns:
            merchant_name = pat["merchant"]
            avg_amt = Decimal(str(pat["approximate_amount"]))

            # Find latest transaction for this merchant in recent 30 days
            latest_tx = (
                db.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.currency == currency,
                    Transaction.merchant == merchant_name,
                    Transaction.transaction_date >= date.today() - timedelta(days=30),
                )
                .order_by(Transaction.transaction_date.desc())
                .first()
            )

            if latest_tx and avg_amt > Decimal("0.00"):
                last_amt = Decimal(str(latest_tx.amount))
                diff_pct = ((last_amt - avg_amt) / avg_amt) * Decimal("100.00")
                if diff_pct >= RECURRING_INCREASE_THRESHOLD_PCT:
                    insights.append(
                        self._build_insight(
                            user_id=user_id,
                            currency=currency,
                            insight_type="RECURRING_EXPENSE_INCREASE",
                            severity="LOW",
                            title=f"Recurring expense for {merchant_name} increased by {_two_dp(diff_pct)}%",
                            description=(
                                f"Latest charge from {merchant_name} ({currency} {_two_dp(last_amt)}) "
                                f"exceeds its historical average ({currency} {_two_dp(avg_amt)})."
                            ),
                            metric="recurring_merchant_amount",
                            current_value=last_amt,
                            baseline_value=avg_amt,
                            change_amount=last_amt - avg_amt,
                            change_percent=_two_dp(diff_pct),
                            period_label="Latest vs Historical Merchant Average",
                            confidence=confidence,
                            details={"merchant": merchant_name, "occurrences": pat["occurrence_count"]},
                        )
                    )

        return insights

    def _build_insight(
        self,
        user_id: uuid.UUID,
        currency: str,
        insight_type: str,
        severity: str,
        title: str,
        description: str,
        metric: str,
        current_value: Decimal,
        baseline_value: Decimal,
        change_amount: Decimal,
        change_percent: Optional[Decimal],
        period_label: str,
        confidence: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> ProactiveInsight:
        """Construct a deterministic ProactiveInsight object with deterministic unique ID for deduplication."""
        raw_id_str = f"{user_id}_{currency}_{insight_type}_{metric}_{_two_dp(current_value)}_{_two_dp(baseline_value)}"
        insight_id = hashlib.sha256(raw_id_str.encode("utf-8")).hexdigest()[:16]

        evidence = InsightEvidence(
            metric=metric,
            current_value=_two_dp(current_value),
            baseline_value=_two_dp(baseline_value),
            change_amount=_two_dp(change_amount),
            change_percent=_two_dp(change_percent) if change_percent is not None else None,
            period_label=period_label,
            details=details or {},
        )

        return ProactiveInsight(
            id=insight_id,
            insight_type=insight_type,
            severity=severity,
            title=title,
            description=description,
            currency=currency,
            evidence=evidence,
            confidence=confidence,
            created_at=datetime.now(timezone.utc),
        )

    # -----------------------------------------------------------------------
    # AI Explanation Integration
    # -----------------------------------------------------------------------

    async def explain_proactive_insight(
        self,
        db: Session,
        user_id: uuid.UUID,
        request_data: ProactiveExplainRequest,
    ) -> ProactiveExplainResponse:
        """Generate a natural language AI explanation for a deterministic proactive insight.

        Rules:
          - Evaluates prompt injection on user question if provided.
          - Wraps verified insight & evidence in XML trust boundary.
          - Does NOT invent metrics or financial claims.
          - Falls back gracefully if LLM provider fails or is disabled.
        """
        # 1. Re-generate user's current proactive insights to find target insight
        res = self.generate_proactive_insights(db=db, user_id=user_id)
        target_insight = next(
            (i for i in res.insights if i.id == request_data.insight_id), None
        )

        if not target_insight:
            return ProactiveExplainResponse(
                insight_id=request_data.insight_id,
                insight_type="UNKNOWN",
                explanation="The requested insight was not found or is no longer active based on your current data.",
                ai_status="fallback_not_found",
                ai_status_message="Insight ID not found in current analysis.",
            )

        # 2. Safety Check on user question if provided
        if request_data.question:
            is_inj, inj_detail = detect_prompt_injection(request_data.question)
            if is_inj:
                logger.warning(
                    f"Prompt injection detected in proactive explain request: {inj_detail}"
                )
                return ProactiveExplainResponse(
                    insight_id=target_insight.id,
                    insight_type=target_insight.insight_type,
                    explanation=(
                        "I cannot fulfill requests that attempt to override safety rules or prompt instructions. "
                        "The deterministic financial metrics remain available above."
                    ),
                    ai_status="blocked_safety_violation",
                    ai_status_message=f"Request blocked by AI Safety Layer: {inj_detail}",
                )

        # 3. Format verified evidence into XML trust boundary for LLM context
        evidence = target_insight.evidence
        xml_context = f"""<verified_proactive_insight>
  <id>{target_insight.id}</id>
  <type>{target_insight.insight_type}</type>
  <severity>{target_insight.severity}</severity>
  <currency>{target_insight.currency}</currency>
  <title>{sanitize_untrusted_content(target_insight.title, tag="title")}</title>
  <description>{sanitize_untrusted_content(target_insight.description, tag="description")}</description>
  <evidence>
    <metric>{evidence.metric}</metric>
    <current_value>{evidence.current_value}</current_value>
    <baseline_value>{evidence.baseline_value}</baseline_value>
    <change_amount>{evidence.change_amount}</change_amount>
    <change_percent>{evidence.change_percent}</change_percent>
    <period_label>{evidence.period_label}</period_label>
  </evidence>
</verified_proactive_insight>"""

        system_instruction = (
            "You are an AI Financial Assistant explaining a verified proactive insight to the user. "
            "You MUST rely ONLY on the verified data in the <verified_proactive_insight> tag. "
            "Explain what the metric change means in plain terms. "
            "Do NOT invent financial figures, do NOT make investment recommendations, and do NOT claim statistical certainty. "
            "Remind the user that the deterministic metrics are the source of truth."
        )

        user_prompt = f"{xml_context}\n\nPlease explain this proactive insight in simple, practical terms."
        if request_data.question:
            safe_q = sanitize_untrusted_content(request_data.question, tag="user_question")
            user_prompt += f"\nUser's specific question: {safe_q}"

        # 4. Call LLM provider with fallback handling
        provider = self._get_provider()
        if not provider:
            return ProactiveExplainResponse(
                insight_id=target_insight.id,
                insight_type=target_insight.insight_type,
                explanation=(
                    f"AI explanation service is currently disabled. "
                    f"Verified evidence: {target_insight.title}. {target_insight.description}"
                ),
                ai_status="fallback_disabled",
                ai_status_message="LLM provider is not configured or disabled.",
            )

        try:
            ai_text = await provider.generate(prompt=user_prompt, system_prompt=system_instruction)
            return ProactiveExplainResponse(
                insight_id=target_insight.id,
                insight_type=target_insight.insight_type,
                explanation=ai_text,
                ai_status="success",
                ai_status_message="Successfully generated AI explanation.",
            )
        except LLMProviderError as e:
            logger.error(f"LLM provider error in proactive explain: {e}")
            return ProactiveExplainResponse(
                insight_id=target_insight.id,
                insight_type=target_insight.insight_type,
                explanation=(
                    f"AI explanation is temporarily unavailable. "
                    f"Verified evidence: {target_insight.title}. {target_insight.description}"
                ),
                ai_status="fallback_unavailable",
                ai_status_message=f"LLM provider unavailable: {str(e)}",
            )
        except Exception as e:
            logger.error(f"Unexpected error in proactive explain: {e}")
            return ProactiveExplainResponse(
                insight_id=target_insight.id,
                insight_type=target_insight.insight_type,
                explanation=(
                    f"AI explanation is temporarily unavailable. "
                    f"Verified evidence: {target_insight.title}. {target_insight.description}"
                ),
                ai_status="fallback_unavailable",
                ai_status_message=f"LLM provider error: {str(e)}",
            )


# Global singleton service instance
proactive_intelligence_service = ProactiveIntelligenceService()
