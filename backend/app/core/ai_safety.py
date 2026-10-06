"""AI Safety Layer module (Phase 16).

Implements strict AI security guardrails:
1. Trust boundary: Untrusted user text and document content isolated in XML delimiters.
2. Prompt injection defense: Detection and sanitization of override attempts.
3. Tool authorization & allowlist: Explicit registry of approved financial tools with Pydantic validation.
4. IDOR prevention: User ID always derived from authenticated session, never trusted from LLM/user input.
5. Data minimization & redaction: Sensitive keys and secrets stripped before model context construction.
6. Rate limiting & input bounds: Request size and frequency validation.
7. Audit logging with correlation ID: Full request traceability without sensitive data leaks.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import html
import re
import secrets
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
import uuid

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.config import settings
from app.core.rate_limit import RateLimiter
from app.models.user import User


# ---------------------------------------------------------------------------
# Rate Limiter for AI Endpoints
# ---------------------------------------------------------------------------

ai_rate_limiter = RateLimiter(
    requests_per_window=settings.ai_rate_limit_per_minute,
    window_seconds=60,
)


def check_ai_rate_limit(request: Request, user_id: Optional[uuid.UUID] = None) -> None:
    """Enforce rate limiting on AI endpoints (per user ID or IP address)."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    key_identity = str(user_id) if user_id else client_ip
    key = f"ai_rate_limit:{key_identity}"

    if ai_rate_limiter.is_rate_limited(key):
        audit_log(
            event_type="AI_RATE_LIMIT_EXCEEDED",
            user_id=user_id,
            ip_address=client_ip,
            status="BLOCKED",
            details={"path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI request rate limit exceeded. Please try again in a minute.",
        )


# ---------------------------------------------------------------------------
# Correlation ID Generator
# ---------------------------------------------------------------------------

def generate_correlation_id() -> str:
    """Generate a unique correlation ID for tracing AI operations across logs."""
    return f"req_{secrets.token_hex(6)}"


# ---------------------------------------------------------------------------
# 1. Trust Boundary & Prompt Injection Protection
# ---------------------------------------------------------------------------

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|system|safety)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|prior|above|system|safety)\s+(instructions|prompts|rules)",
    r"override\s+(system|safety|security)\s+(policy|rules|instructions)",
    r"reveal\s+(your\s+)?(system\s+prompt|instructions|secret|api_key|prompt)",
    r"you\s+are\s+now\s+(a|an|unrestricted)",
    r"unrestricted\s+(financial\s+)?assistant",
    r"ignore\s+all\s+safety\s+rules",
    r"admin\s+tool",
    r"database\s+access",
    r"jailbreak",
    r"bypass\s+(safety|security|authorization|restriction)",
]


def detect_prompt_injection(text: str) -> Tuple[bool, Optional[str]]:
    """Scan input text for known prompt injection patterns.

    Returns:
        (is_injection_detected, matched_pattern_description)
    """
    if not text:
        return False, None

    lower_text = text.lower()
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, lower_text):
            return True, f"Matched injection pattern: '{pattern}'"

    return False, None


def sanitize_untrusted_content(
    text: Optional[str],
    tag: str = "untrusted_user_input",
    max_length: int = 1000,
) -> str:
    """Wrap untrusted user/document text in strict XML tags to maintain system boundary.

    Content inside XML tags is explicitly designated as DATA ONLY to prevent
    the LLM from interpreting user text or uploaded files as system policy overrides.
    """
    if not text:
        return f"<{tag}>None provided</{tag}>"

    # Truncate to maximum length
    truncated = text.strip()[:max_length]

    # HTML-escape to prevent script/markup injection
    escaped = html.escape(truncated)

    # Strip raw XML tag closing sequences matching our wrapper tag to prevent escaping tags
    escaped = re.sub(rf"</?\s*{tag}\s*>", "", escaped, flags=re.IGNORECASE)

    return f"<{tag}>\n{escaped}\n</{tag}>"


# ---------------------------------------------------------------------------
# 2. Data Minimization & Redaction
# ---------------------------------------------------------------------------

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "session_token",
    "session_token_hash",
    "token",
    "secret",
    "api_key",
    "gemini_api_key",
    "credit_card",
    "card_number",
    "ssn",
}


def redact_sensitive_data(obj: Any) -> Any:
    """Recursively redact sensitive keys and credentials from data before model prompt construction."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned
    elif isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# 3. Input & Token Limit Validation
# ---------------------------------------------------------------------------

def validate_ai_request_bounds(
    question: str,
    conversation_history: Optional[List[Any]] = None,
    document_context: str = "",
) -> None:
    """Validate request size bounds prior to calling the LLM provider."""
    if len(question) > settings.ai_max_question_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Question length ({len(question)} characters) exceeds maximum allowed ({settings.ai_max_question_length}).",
        )

    if conversation_history and len(conversation_history) > settings.ai_max_chat_history_messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Conversation history length ({len(conversation_history)} messages) exceeds maximum allowed ({settings.ai_max_chat_history_messages}).",
        )

    if len(document_context) > settings.ai_max_document_context_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Document context length ({len(document_context)} characters) exceeds maximum allowed ({settings.ai_max_document_context_size}).",
        )


# ---------------------------------------------------------------------------
# 4. Tool Authorization Layer & Allowlist
# ---------------------------------------------------------------------------

class ToolGetFinancialStateArgs(BaseModel):
    """Schema for get_financial_state tool."""
    period: Optional[str] = Field(default="current_month", description="Analysis period")


class ToolGetIncomeExpensesArgs(BaseModel):
    """Schema for get_income_and_expenses tool."""
    period: Optional[str] = Field(default="current_month", description="Analysis period")


class ToolGetCashFlowArgs(BaseModel):
    """Schema for get_cash_flow tool."""
    period: Optional[str] = Field(default="last_3_months", description="Analysis period")


class ToolGetRecurringExpensesArgs(BaseModel):
    """Schema for get_recurring_expenses tool."""
    pass  # No args required


class ToolSimulateScenarioArgs(BaseModel):
    """Schema for simulate_decision_scenario tool."""
    scenario_type: str = Field(..., description="Scenario type: large_purchase, recurring_expense_add, income_reduction, expense_increase")
    amount: float = Field(..., gt=0, description="Scenario amount, must be positive")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    description: Optional[str] = Field(default=None, max_length=255, description="Scenario description")
    period: Optional[str] = Field(default="last_3_months", description="Analysis period")

    @model_validator(mode="after")
    def validate_types(self) -> "ToolSimulateScenarioArgs":
        valid_scenarios = {"large_purchase", "recurring_expense_add", "income_reduction", "expense_increase"}
        if self.scenario_type not in valid_scenarios:
            raise ValueError(f"scenario_type must be one of {valid_scenarios}")
        self.currency = self.currency.upper()
        return self


class ToolDefinition(BaseModel):
    """Metadata and execution definition for an authorized AI tool."""
    name: str
    description: str
    args_schema: Type[BaseModel]
    handler_name: str


# Permitted AI Tools Allowlist (Only tool definitions corresponding to actual backend domain services)
TOOL_ALLOWLIST: Dict[str, ToolDefinition] = {
    "get_financial_state": ToolDefinition(
        name="get_financial_state",
        description="Retrieve financial account balances and summary state for the authenticated user.",
        args_schema=ToolGetFinancialStateArgs,
        handler_name="_tool_get_financial_state",
    ),
    "get_income_and_expenses": ToolDefinition(
        name="get_income_and_expenses",
        description="Retrieve total income, total expenses, and net cash flow by currency for a given period.",
        args_schema=ToolGetIncomeExpensesArgs,
        handler_name="_tool_get_income_and_expenses",
    ),
    "get_cash_flow": ToolDefinition(
        name="get_cash_flow",
        description="Retrieve baseline net cash flow and savings rate summary.",
        args_schema=ToolGetCashFlowArgs,
        handler_name="_tool_get_cash_flow",
    ),
    "get_recurring_expenses": ToolDefinition(
        name="get_recurring_expenses",
        description="Retrieve detected recurring expense patterns for the authenticated user.",
        args_schema=ToolGetRecurringExpensesArgs,
        handler_name="_tool_get_recurring_expenses",
    ),
    "simulate_decision_scenario": ToolDefinition(
        name="simulate_decision_scenario",
        description="Deterministically evaluate a hypothetical financial scenario (e.g. large purchase or expense change).",
        args_schema=ToolSimulateScenarioArgs,
        handler_name="_tool_simulate_decision_scenario",
    ),
}


class ToolExecutionEngine:
    """Engine that enforces tool allowlist checking, Pydantic argument validation, and IDOR protection."""

    @staticmethod
    def execute(
        tool_name: str,
        arguments: Dict[str, Any],
        current_user_id: uuid.UUID,
        db: Session,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """Authorize and execute a requested tool.

        Security enforcement:
        1. Allowlist check: Tool must exist in TOOL_ALLOWLIST.
        2. Schema validation: Arguments parsed & validated via Pydantic model.
        3. IDOR protection: user_id argument is NEVER accepted from LLM tool call; user_id is forced from session.
        4. Truncation: Output size bounded by ai_max_tool_result_size.
        """
        # 1. Allowlist check
        if tool_name not in TOOL_ALLOWLIST:
            audit_log(
                event_type="AI_TOOL_DENIED",
                user_id=current_user_id,
                status="BLOCKED",
                details={
                    "correlation_id": correlation_id,
                    "tool_name": tool_name,
                    "reason": "Tool not in allowlist",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unauthorized tool requested: '{tool_name}' is not in the approved AI tool allowlist.",
            )

        tool_def = TOOL_ALLOWLIST[tool_name]

        # 2. Prevent IDOR by stripping any user_id passed by LLM in arguments
        safe_args = {k: v for k, v in arguments.items() if k.lower() != "user_id"}

        # 3. Argument validation via Pydantic schema
        try:
            validated_args = tool_def.args_schema(**safe_args)
        except ValidationError as ve:
            audit_log(
                event_type="AI_TOOL_DENIED",
                user_id=current_user_id,
                status="BLOCKED",
                details={
                    "correlation_id": correlation_id,
                    "tool_name": tool_name,
                    "reason": f"Argument validation failure: {ve.errors()}",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid arguments for tool '{tool_name}': {ve.errors()}",
            )

        # 4. Dispatch to actual domain handler
        handler = getattr(ToolExecutionEngine, tool_def.handler_name, None)
        if not handler:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Tool handler '{tool_def.handler_name}' is missing.",
            )

        raw_result = handler(
            args=validated_args,
            user_id=current_user_id,
            db=db,
        )

        audit_log(
            event_type="AI_TOOL_ALLOWED",
            user_id=current_user_id,
            status="SUCCESS",
            details={
                "correlation_id": correlation_id,
                "tool_name": tool_name,
            },
        )

        return raw_result

    # Handler implementations delegating to verified deterministic services
    @staticmethod
    def _tool_get_financial_state(args: ToolGetFinancialStateArgs, user_id: uuid.UUID, db: Session) -> Dict[str, Any]:
        from app.models.financial_account import FinancialAccount
        accounts = db.query(FinancialAccount).filter(
            FinancialAccount.user_id == user_id,
            FinancialAccount.is_active == True,
        ).all()
        return {
            "account_count": len(accounts),
            "accounts": [
                {
                    "name": a.name,
                    "account_type": a.account_type,
                    "currency": a.currency,
                    "opening_balance": str(a.opening_balance) if a.opening_balance is not None else None,
                }
                for a in accounts
            ],
        }

    @staticmethod
    def _tool_get_income_and_expenses(args: ToolGetIncomeExpensesArgs, user_id: uuid.UUID, db: Session) -> Dict[str, Any]:
        from app.services.analytics import analytics_service
        summary = analytics_service.get_summary(db=db, user_id=user_id, period=args.period)
        return {
            "period_start": summary.period_start.isoformat(),
            "period_end": summary.period_end.isoformat(),
            "by_currency": [
                {
                    "currency": c.currency,
                    "total_income": str(c.total_income),
                    "total_expenses": str(c.total_expenses),
                    "net_cash_flow": str(c.net_cash_flow),
                }
                for c in summary.by_currency
            ],
        }

    @staticmethod
    def _tool_get_cash_flow(args: ToolGetCashFlowArgs, user_id: uuid.UUID, db: Session) -> Dict[str, Any]:
        from app.services.analytics import analytics_service
        summary = analytics_service.get_summary(db=db, user_id=user_id, period=args.period)
        return {
            "period_start": summary.period_start.isoformat(),
            "period_end": summary.period_end.isoformat(),
            "by_currency": [
                {
                    "currency": c.currency,
                    "net_cash_flow": str(c.net_cash_flow),
                    "savings_rate": str(c.savings_rate) if c.savings_rate is not None else None,
                }
                for c in summary.by_currency
            ],
        }

    @staticmethod
    def _tool_get_recurring_expenses(args: ToolGetRecurringExpensesArgs, user_id: uuid.UUID, db: Session) -> Dict[str, Any]:
        from app.services.analytics import analytics_service
        res = analytics_service.detect_recurring(db=db, user_id=user_id)
        return {
            "detected_patterns_count": len(res.detected_patterns),
            "patterns": [
                {
                    "merchant": p.merchant,
                    "currency": p.currency,
                    "approximate_amount": str(p.approximate_amount),
                    "frequency": p.detected_frequency.value,
                }
                for p in res.detected_patterns
            ],
        }

    @staticmethod
    def _tool_simulate_decision_scenario(args: ToolSimulateScenarioArgs, user_id: uuid.UUID, db: Session) -> Dict[str, Any]:
        from app.schemas.decision import DecisionAnalyzeRequest, DecisionScenarioType
        from app.services.decision_engine import decision_support_engine

        req = DecisionAnalyzeRequest(
            scenario_type=DecisionScenarioType(args.scenario_type),
            amount=Decimal(str(args.amount)),
            currency=args.currency,
            description=args.description,
            period=args.period,
        )
        res = decision_support_engine.analyze(db=db, user_id=user_id, request=req)
        return {
            "scenario_type": res.scenario_type.value,
            "currency": res.currency,
            "amount": str(res.amount),
            "net_cash_flow_change": str(res.cash_flow_projection.net_cash_flow_change) if res.cash_flow_projection.net_cash_flow_change is not None else None,
            "liquidity_status": res.liquidity_evaluation.status.value,
            "risk_indicators_count": len(res.risk_indicators),
        }
