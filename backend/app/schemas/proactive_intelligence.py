"""Pydantic schemas for Phase 18: Proactive Financial Intelligence.

Provides structured contracts for proactive insight detection, evidence payloads,
and optional AI explanations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


class InsightEvidence(BaseModel):
    """Structured, verifiable financial evidence supporting a proactive insight."""

    metric: str = Field(description="Primary metric name evaluated (e.g., 'monthly_expenses').")
    current_value: Decimal = Field(description="Current period metric value.")
    baseline_value: Decimal = Field(description="Historical baseline metric value.")
    change_amount: Decimal = Field(description="Absolute difference (current - baseline).")
    change_percent: Optional[Decimal] = Field(
        default=None, description="Percentage change relative to baseline."
    )
    period_label: str = Field(description="Human-readable description of evaluated periods.")
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Additional context metrics."
    )


class ProactiveInsight(BaseModel):
    """A single deterministic proactive financial insight."""

    id: str = Field(description="Deterministic unique ID for client deduplication.")
    insight_type: str = Field(
        description=(
            "Type of insight: SPENDING_INCREASE, SPENDING_DECREASE, SAVINGS_RATE_DECLINE, "
            "SAVINGS_RATE_IMPROVEMENT, CASH_FLOW_DETERIORATION, CASH_FLOW_IMPROVEMENT, "
            "RECURRING_EXPENSE_INCREASE, INCOME_CHANGE, LIQUIDITY_PRESSURE"
        )
    )
    severity: str = Field(description="Deterministic severity level: INFO, LOW, MEDIUM, HIGH.")
    title: str = Field(description="Factual summary title.")
    description: str = Field(description="Detailed factual description based on verified data.")
    currency: str = Field(description="ISO 4217 currency code.")
    evidence: InsightEvidence = Field(description="Structured evidence supporting this insight.")
    confidence: str = Field(description="Evidence strength based on data coverage: LOW, MEDIUM, HIGH.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Evaluation timestamp."
    )


class ProactiveInsightsResponse(BaseModel):
    """Response payload for GET /api/financial/proactive-insights."""

    total_count: int = Field(description="Total number of insights detected.")
    data_sufficient: bool = Field(description="Whether the user has sufficient financial data for baseline analysis.")
    data_sufficiency_reason: Optional[str] = Field(
        default=None, description="Reason if data is insufficient for proactive analysis."
    )
    currencies_evaluated: List[str] = Field(description="Currencies analyzed.")
    insights: List[ProactiveInsight] = Field(description="List of detected proactive insights.")


class ProactiveExplainRequest(BaseModel):
    """Request model for explaining a proactive insight with AI."""

    insight_id: str = Field(description="ID of the proactive insight to explain.")
    question: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional specific question about the insight.",
    )


class ProactiveExplainResponse(BaseModel):
    """Response payload for AI-explained proactive insight."""

    insight_id: str = Field(description="ID of the explained insight.")
    insight_type: str = Field(description="Type of the insight.")
    explanation: str = Field(description="Natural language explanation derived from evidence.")
    ai_status: str = Field(
        description="AI generation status: 'success', 'fallback_unavailable', 'blocked_safety_violation'."
    )
    ai_status_message: str = Field(description="Status description.")
    disclaimer: str = Field(
        default=(
            "This AI explanation translates deterministic financial metrics into natural language. "
            "It does not provide financial or investment advice. Backend metrics remain the source of truth."
        ),
        description="Standard disclaimer.",
    )
