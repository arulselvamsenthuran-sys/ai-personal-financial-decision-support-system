"""AI Explanation Service for Phase 13.

Translates deterministic DecisionSupportEngine outputs into explainable,
fact-anchored natural language narratives using an LLM.

Engineering rules:
  - The deterministic backend is the sole source of truth for all calculations.
  - The LLM does NOT perform calculations, invent numbers, or give financial advice.
  - User-provided text (e.g. description) is strictly quoted and sanitized.
  - Any LLM failure (timeout, validation failure, API error) falls back gracefully
    without failing the deterministic analysis.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import html
import json
import re
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.schemas.ai_explanation import (
    AIExplanationResult,
    AIExplanationStatus,
    DecisionExplainRequest,
    DecisionExplainResponse,
)
from app.schemas.decision import (
    ComponentAvailabilityStatus,
    DecisionAnalyzeRequest,
    DecisionAnalyzeResponse,
    DecisionScenarioType,
)
from app.services.decision_engine import decision_support_engine
from app.services.llm.provider import (
    BaseLLMProvider,
    LLMProviderError,
    LLMTimeoutError,
    get_llm_provider,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Prompt Engineering & Templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a specialized Financial Explanation Assistant for a personal financial decision support system.
Your job is to translate DETERMINISTIC FINANCIAL ANALYSIS RESULTS into clear, objective, and factual natural language explanations.

STRICT INVARIANTS AND CONSTRAINTS:
1. SOLE SOURCE OF TRUTH: All numbers, percentages, balances, and risk triggers provided in the context are authoritative and final.
2. NO INVENTED NUMBERS: You MUST NOT invent, calculate, round differently, or alter any numeric facts.
3. NO FINANCIAL OR INVESTMENT ADVICE: You must never say 'You should buy this', 'You cannot afford this', or give financial/investment advice. Use neutral, analytical language (e.g., 'The deterministic analysis shows that...', 'Under this scenario...').
4. SCENARIO DISTINCTION:
   - For 'large_purchase': Treat as a ONE-TIME financial event. Monthly recurring expenses remain unchanged.
   - For recurring scenarios ('recurring_expense_add', 'income_reduction', 'expense_increase'): Acknowledge permanent ongoing monthly impact.
5. LIQUIDITY SAFETY:
   - If liquidity_data is 'unavailable' or 'partial', you MUST state that verified liquid account balance data is unavailable or incomplete. DO NOT say 'you have no money' or assume a zero balance.
6. JSON FORMAT ONLY: You MUST respond ONLY with a valid JSON object matching this schema:
{
  "summary": "High-level factual narrative summarizing the decision analysis.",
  "cash_flow_impact_narrative": "Clear explanation of historical baseline vs. scenario projection, noting one-time vs recurring nature.",
  "liquidity_narrative": "Factual explanation of liquid balance and coverage, or explicit acknowledgement that liquidity data is unavailable.",
  "key_tradeoffs": ["Factual bullet point 1", "Factual bullet point 2"],
  "data_limitations_noted": ["Data boundary note 1", "Data boundary note 2"]
}
"""


def _sanitize_user_text(text: Optional[str]) -> str:
    """Sanitize user input to prevent prompt injection and formatting issues."""
    if not text:
        return "None provided"
    # Strip dangerous characters and html-escape
    cleaned = re.sub(r"[\r\n\t]+", " ", text).strip()
    return f'"{html.escape(cleaned[:255])}"'


class AIExplanationService:
    """Service that coordinates deterministic decision evaluation and LLM narrative generation."""

    def __init__(self, provider: Optional[BaseLLMProvider] = None):
        self._default_provider = provider

    def _get_provider(self, override: Optional[BaseLLMProvider] = None) -> Optional[BaseLLMProvider]:
        if override is not None:
            return override
        if self._default_provider is not None:
            return self._default_provider
        return get_llm_provider()

    def _build_user_prompt(self, analysis: DecisionAnalyzeResponse) -> str:
        """Construct a structured, factual prompt from the deterministic analysis response."""
        data_audit = analysis.data_availability
        cf = analysis.cash_flow_projection
        liq = analysis.liquidity_evaluation

        prompt_dict: Dict[str, Any] = {
            "scenario": {
                "type": analysis.scenario_type.value,
                "amount": str(analysis.amount),
                "currency": analysis.currency,
                "user_description": _sanitize_user_text(analysis.description),
                "period": f"{analysis.period_start} to {analysis.period_end}",
            },
            "data_availability": {
                "overall_status": data_audit.overall_status.value,
                "transaction_baseline": data_audit.transaction_baseline.value,
                "liquidity_data": data_audit.liquidity_data.value,
                "transaction_count": data_audit.transaction_count,
                "notes": data_audit.notes,
            },
            "cash_flow_projection": {
                "baseline_income": str(cf.baseline_income) if cf.baseline_income is not None else None,
                "baseline_expenses": str(cf.baseline_expenses) if cf.baseline_expenses is not None else None,
                "baseline_net_cash_flow": str(cf.baseline_net_cash_flow) if cf.baseline_net_cash_flow is not None else None,
                "baseline_savings_rate_pct": str(cf.baseline_savings_rate) if cf.baseline_savings_rate is not None else None,
                "projected_income": str(cf.projected_income) if cf.projected_income is not None else None,
                "projected_expenses": str(cf.projected_expenses) if cf.projected_expenses is not None else None,
                "projected_net_cash_flow": str(cf.projected_net_cash_flow) if cf.projected_net_cash_flow is not None else None,
                "projected_savings_rate_pct": str(cf.projected_savings_rate) if cf.projected_savings_rate is not None else None,
                "net_cash_flow_change": str(cf.net_cash_flow_change) if cf.net_cash_flow_change is not None else None,
                "savings_rate_change_pct_points": str(cf.savings_rate_change) if cf.savings_rate_change is not None else None,
                "is_one_time_impact": cf.is_one_time_impact,
                "impact_summary": cf.impact_summary,
            },
            "liquidity_evaluation": {
                "status": liq.status.value,
                "known_liquid_balance": str(liq.known_liquid_balance) if liq.known_liquid_balance is not None else None,
                "projected_balance_after": str(liq.projected_balance_after) if liq.projected_balance_after is not None else None,
                "liquidity_coverage_ratio": str(liq.liquidity_coverage_ratio) if liq.liquidity_coverage_ratio is not None else None,
                "is_liquid_balance_sufficient": liq.is_liquid_balance_sufficient,
                "explanation": liq.explanation,
            },
            "risk_indicators": [
                {
                    "code": r.code,
                    "severity": r.severity,
                    "message": r.message,
                    "rule": r.deterministic_rule,
                    "trigger_value": r.trigger_value,
                }
                for r in analysis.risk_indicators
            ],
            "warnings": analysis.warnings,
        }

        return f"DETERMINISTIC EVALUATION FACTS (JSON FORMAT):\n{json.dumps(prompt_dict, indent=2)}\n\nPlease provide the factual natural-language explanation as instructed."

    def _validate_explanation_output(
        self,
        raw_json_str: str,
        provider: BaseLLMProvider,
        analysis: DecisionAnalyzeResponse,
    ) -> AIExplanationResult:
        """Parse and validate the JSON output from the LLM."""
        logger.debug("Raw LLM Response before parsing: %r", raw_json_str)
        cleaned_json = raw_json_str.strip()
        if cleaned_json.startswith("```"):
            lines = cleaned_json.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned_json = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned_json)
        except Exception as e:
            logger.warning("Malformed JSON from LLM (%s). Raw output preview: %r", e, cleaned_json[:300])
            raise ValueError(f"Malformed JSON from LLM: {e}")

        summary = data.get("summary")
        cash_flow_narrative = data.get("cash_flow_impact_narrative")
        liquidity_narrative = data.get("liquidity_narrative")
        tradeoffs = data.get("key_tradeoffs", [])
        limitations = data.get("data_limitations_noted", [])

        if not summary or not isinstance(summary, str):
            raise ValueError("Missing or invalid 'summary' in LLM response.")
        if not cash_flow_narrative or not isinstance(cash_flow_narrative, str):
            raise ValueError("Missing or invalid 'cash_flow_impact_narrative' in LLM response.")
        if not liquidity_narrative or not isinstance(liquidity_narrative, str):
            raise ValueError("Missing or invalid 'liquidity_narrative' in LLM response.")
        if not isinstance(tradeoffs, list):
            tradeoffs = [str(tradeoffs)]
        if not isinstance(limitations, list):
            limitations = [str(limitations)]

        # Liquidity guardrail check:
        # If liquidity is unavailable, verify the LLM doesn't assert a 0 balance or 'no money'
        if analysis.liquidity_evaluation.status == ComponentAvailabilityStatus.UNAVAILABLE:
            lower_liq = liquidity_narrative.lower()
            if "0.00" in lower_liq and "unavailable" not in lower_liq:
                logger.warning("LLM liquidity narrative asserted 0 balance when data is unavailable")

        return AIExplanationResult(
            summary=summary.strip(),
            cash_flow_impact_narrative=cash_flow_narrative.strip(),
            liquidity_narrative=liquidity_narrative.strip(),
            key_tradeoffs=[str(t).strip() for t in tradeoffs if t],
            data_limitations_noted=[str(l).strip() for l in limitations if l],
            provider=provider.provider_name,
            model=provider.model_name,
        )

    async def explain(
        self,
        db: Session,
        user_id: uuid.UUID,
        request: DecisionExplainRequest,
        period_start: date,
        period_end: date,
        provider_override: Optional[BaseLLMProvider] = None,
    ) -> DecisionExplainResponse:
        """Execute deterministic evaluation first, then generate natural language explanation.

        Falls back gracefully if the LLM provider fails or is disabled.
        """
        # 1. Authoritative deterministic evaluation (Phase 12 engine)
        analyze_req = DecisionAnalyzeRequest(
            scenario_type=request.scenario_type,
            amount=request.amount,
            currency=request.currency,
            description=request.description,
            period=request.period,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        deterministic_result = decision_support_engine.analyze(
            db=db,
            user_id=user_id,
            request=analyze_req,
            period_start=period_start,
            period_end=period_end,
        )

        # 2. Check provider availability
        provider = self._get_provider(override=provider_override)
        if provider is None:
            return DecisionExplainResponse(
                deterministic_analysis=deterministic_result,
                ai_explanation=None,
                ai_status=AIExplanationStatus.FALLBACK_DISABLED,
                ai_status_message="AI explanation is disabled or no LLM provider configured.",
            )

        # 3. Generate explanation
        user_prompt = self._build_user_prompt(deterministic_result)

        try:
            raw_output = await provider.generate(
                prompt=user_prompt,
                system_prompt=SYSTEM_PROMPT,
            )

            explanation_result = self._validate_explanation_output(
                raw_json_str=raw_output,
                provider=provider,
                analysis=deterministic_result,
            )

            return DecisionExplainResponse(
                deterministic_analysis=deterministic_result,
                ai_explanation=explanation_result,
                ai_status=AIExplanationStatus.SUCCESS,
                ai_status_message="AI explanation successfully generated and validated.",
            )

        except LLMTimeoutError as e:
            logger.warning("AI explanation timed out: %s", e)
            return DecisionExplainResponse(
                deterministic_analysis=deterministic_result,
                ai_explanation=None,
                ai_status=AIExplanationStatus.FALLBACK_TIMEOUT,
                ai_status_message=f"AI explanation generation timed out: {e}",
            )
        except LLMProviderError as e:
            logger.warning("AI explanation provider error: %s", e)
            return DecisionExplainResponse(
                deterministic_analysis=deterministic_result,
                ai_explanation=None,
                ai_status=AIExplanationStatus.FALLBACK_PROVIDER_ERROR,
                ai_status_message=f"AI explanation provider error: {e}",
            )
        except ValueError as e:
            logger.warning("AI explanation validation failed: %s", e)
            return DecisionExplainResponse(
                deterministic_analysis=deterministic_result,
                ai_explanation=None,
                ai_status=AIExplanationStatus.FALLBACK_VALIDATION_FAILED,
                ai_status_message=f"AI explanation validation failed: {e}",
            )
        except Exception as e:
            logger.error("Unexpected error during AI explanation: %s", e)
            return DecisionExplainResponse(
                deterministic_analysis=deterministic_result,
                ai_explanation=None,
                ai_status=AIExplanationStatus.FALLBACK_PROVIDER_ERROR,
                ai_status_message=f"Unexpected error generating AI explanation: {e}",
            )


# Module-level singleton
ai_explanation_service = AIExplanationService()
