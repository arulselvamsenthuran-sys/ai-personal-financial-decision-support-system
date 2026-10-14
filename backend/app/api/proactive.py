"""Phase 18: Proactive Financial Intelligence API routes.

Endpoints:
- GET  /api/financial/proactive-insights        — Retrieve proactive insights
- POST /api/financial/proactive-insights/explain — AI-generated explanation for an insight
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.ai_safety import check_ai_rate_limit
from app.models.user import User
from app.schemas.proactive_intelligence import (
    ProactiveExplainRequest,
    ProactiveExplainResponse,
    ProactiveInsightsResponse,
)
from app.services.proactive_intelligence import proactive_intelligence_service

router = APIRouter(prefix="/api/financial/proactive-insights", tags=["proactive-intelligence"])


@router.get(
    "",
    response_model=ProactiveInsightsResponse,
    summary="[Phase 18] Get proactive financial insights",
)
def get_proactive_insights(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProactiveInsightsResponse:
    """Retrieve proactive financial insights for the authenticated user.

    Security Invariants:
    - Session authentication required.
    - Scoped strictly by authenticated user_id (IDOR protection).
    - Read-only, deterministic calculation over verified transaction data.
    - Multi-currency isolated.
    - Data sufficiency enforced (suppresses false alarms when data is sparse).
    """
    return proactive_intelligence_service.generate_proactive_insights(
        db=db,
        user_id=current_user.id,
    )


@router.post(
    "/explain",
    response_model=ProactiveExplainResponse,
    summary="[Phase 18] Explain proactive insight with AI",
)
async def explain_proactive_insight(
    request_data: ProactiveExplainRequest,
    req: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProactiveExplainResponse:
    """Generate a natural language explanation for a proactive insight using AI.

    Security Invariants:
    - Session authentication required.
    - AI rate limiting enforced.
    - Prompt injection check on optional user question.
    - Evidence wrapped in XML trust boundary.
    - Graceful fallback if LLM provider is unavailable.
    """
    check_ai_rate_limit(request=req, user_id=current_user.id)

    return await proactive_intelligence_service.explain_proactive_insight(
        db=db,
        user_id=current_user.id,
        request_data=request_data,
    )
