"""Financial API routes for Phase 6, Phase 8, Phase 9, Phase 10, and Phase 11 financial data models."""

from datetime import date, timedelta
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_user_account
from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.financial_event import FinancialEvent
from app.models.financial_insight import FinancialInsight  # Phase 10
from app.models.ledger import LedgerAccount, LedgerEntry  # Phase 9
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.analytics import (  # Phase 10
    AnalyticsSummaryByCurrency,
    AnalyticsSummaryResponse,
    CategoryBreakdownItem,
    CategoryBreakdownResponse,
    FinancialInsightResponse,
    InsightsListResponse,
    MonthlyAnalyticsResponse,
    MonthlyDataByCurrency,
    RecurringTransactionItem,
    RecurringTransactionsResponse,
)
from app.schemas.financial import (
    FinancialAccountResponse,
    FinancialDocumentResponse,
    FinancialEventResponse,
    LedgerAccountResponse,
    LedgerBalanceResponse,
    LedgerEntryResponse,
    ReplaySummaryResponse,
    TransactionCreate,
    TransactionResponse,
)
from app.schemas.decision import (  # Phase 12
    DecisionAnalyzeRequest,
    DecisionAnalyzeResponse,
)
from app.schemas.ai_explanation import (  # Phase 13
    DecisionExplainRequest,
    DecisionExplainResponse,
)
from app.schemas.chat import (  # Phase 15
    DecisionChatRequest,
    DecisionChatResponse,
)
from app.schemas.scenario import (  # Phase 11
    ScenarioSimulateRequest,
    ScenarioSimulateResponse,
)
from app.services.decision_engine import decision_support_engine  # Phase 12
from app.services.llm.service import ai_explanation_service  # Phase 13
from app.services.document_service import document_ingestion_service
from app.services.financial_intelligence import (  # Phase 10
    DateRange,
    current_month_range,
    last_n_months_range,
    previous_month_range,
    financial_intelligence_service,
)
from app.services.insight_service import insight_service  # Phase 10
from app.services.ledger_validation import ledger_validation_service  # Phase 9
from app.services.replay_service import replay_service
from app.services.scenario_service import scenario_simulation_service  # Phase 11


router = APIRouter(prefix="/api/financial", tags=["financial"])


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

_PERIOD_OPTIONS = {
    "current_month": current_month_range,
    "previous_month": previous_month_range,
    "last_30_days": lambda: last_n_months_range(1),
    "last_3_months": lambda: last_n_months_range(3),
    "last_6_months": lambda: last_n_months_range(6),
    "last_12_months": lambda: last_n_months_range(12),
}


def _resolve_date_range(
    period: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> DateRange:
    """Resolve query parameters into a DateRange.

    Priority: explicit start_date/end_date > period preset > current_month default.
    """
    if start_date and end_date:
        if start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="start_date must not be after end_date.",
            )
        return DateRange(start_date, end_date)

    if period:
        if period not in _PERIOD_OPTIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid period '{period}'. "
                    f"Valid values: {', '.join(_PERIOD_OPTIONS.keys())}."
                ),
            )
        return _PERIOD_OPTIONS[period]()

    # Default: current month
    return current_month_range()


@router.get(
    "/accounts",
    response_model=List[FinancialAccountResponse],
    summary="List authenticated user's financial accounts",
)
def list_financial_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[FinancialAccount]:
    """Retrieve financial accounts owned by the authenticated user."""
    accounts = (
        db.query(FinancialAccount)
        .filter(FinancialAccount.user_id == current_user.id)
        .order_by(FinancialAccount.created_at.desc())
        .all()
    )
    return accounts


@router.get(
    "/transactions",
    response_model=List[TransactionResponse],
    summary="List authenticated user's transactions",
)
def list_transactions(
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by specific financial account ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Transaction]:
    """Retrieve transactions owned by the authenticated user.
    
    If account_id is provided, ownership of that account is validated first.
    """
    if account_id:
        # Validate that the specified account belongs to the authenticated user
        get_user_account(account_id=account_id, current_user=current_user, db=db)
        transactions = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == current_user.id,
                Transaction.financial_account_id == account_id,
            )
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .all()
        )
    else:
        transactions = (
            db.query(Transaction)
            .filter(Transaction.user_id == current_user.id)
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .all()
        )
    return transactions


@router.post(
    "/transactions",
    response_model=TransactionResponse,
    status_code=201,
    summary="[Phase 15] Create a new transaction for the authenticated user",
)
def create_transaction(
    request: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """Create a transaction under the authenticated user's account.

    Security invariants:
    - user_id is derived from the session (never from the request body).
    - Account ownership is enforced: the target financial_account_id must
      belong to the authenticated user.
    - Currency consistency: the transaction currency must match the target
      account's currency.
    - All financial calculations downstream remain the backend's responsibility.
    """
    # 1. Verify account ownership (raises 404 if not owned by current_user)
    account = get_user_account(
        account_id=request.financial_account_id,
        current_user=current_user,
        db=db,
    )

    # 2. Enforce currency consistency with account
    if request.currency.upper() != account.currency.upper():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Currency mismatch: transaction currency '{request.currency}' "
                f"does not match account currency '{account.currency}'."
            ),
        )

    # 3. Create the transaction — user_id from session, NOT from request
    txn = Transaction(
        user_id=current_user.id,
        financial_account_id=request.financial_account_id,
        transaction_date=request.transaction_date,
        posted_at=request.posted_at,
        amount=request.amount,
        currency=request.currency.upper(),
        transaction_type=request.transaction_type,
        merchant=request.merchant,
        description=request.description,
        reference=request.reference,
        category=request.category,
        subcategory=request.subcategory,
        status=request.status,
        source="manual",
        notes=request.notes,
        metadata_json=request.metadata_json,
    )

    db.add(txn)
    db.commit()
    db.refresh(txn)

    return txn


@router.get(
    "/documents",
    response_model=List[FinancialDocumentResponse],
    summary="List authenticated user's financial documents",
)
def list_financial_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[FinancialDocument]:
    """Retrieve financial documents owned by the authenticated user."""
    documents = (
        db.query(FinancialDocument)
        .filter(FinancialDocument.user_id == current_user.id)
        .order_by(FinancialDocument.uploaded_at.desc())
        .all()
    )
    return documents


@router.post(
    "/documents",
    response_model=FinancialDocumentResponse,
    status_code=201,
    summary="Upload and ingest a financial document (CSV/PDF)",
)
def upload_financial_document(
    account_id: uuid.UUID = Query(..., description="Target financial account ID"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancialDocument:
    """Upload and parse a financial statement document (CSV or PDF)."""
    return document_ingestion_service.process_document_upload(
        db=db,
        user=current_user,
        account_id=account_id,
        file=file,
    )


@router.get(
    "/events",
    response_model=List[FinancialEventResponse],
    summary="List authenticated user's immutable financial events",
)
def list_financial_events(
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by financial account ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[FinancialEvent]:
    """Retrieve financial events for the authenticated user."""
    if account_id:
        get_user_account(account_id=account_id, current_user=current_user, db=db)
        events = (
            db.query(FinancialEvent)
            .filter(
                FinancialEvent.user_id == current_user.id,
                FinancialEvent.financial_account_id == account_id,
            )
            .order_by(FinancialEvent.created_at.desc())
            .all()
        )
    else:
        events = (
            db.query(FinancialEvent)
            .filter(FinancialEvent.user_id == current_user.id)
            .order_by(FinancialEvent.created_at.desc())
            .all()
        )
    return events


@router.get(
    "/replay",
    response_model=ReplaySummaryResponse,
    summary="Replay account financial events and transactions",
)
def replay_account_events(
    account_id: uuid.UUID = Query(..., description="Financial account ID to replay"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Replay financial events for a financial account and return summary metrics."""
    return replay_service.replay_account(
        db=db,
        user_id=current_user.id,
        financial_account_id=account_id,
    )


# ============================================================================
# Phase 9 – Double-Entry Ledger Endpoints
# ============================================================================

@router.get(
    "/ledger/accounts",
    response_model=List[LedgerAccountResponse],
    summary="List the authenticated user's ledger accounts (chart of accounts)",
)
def list_ledger_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[LedgerAccount]:
    """Return all ledger accounts owned by the authenticated user."""
    accounts = (
        db.query(LedgerAccount)
        .filter(LedgerAccount.user_id == current_user.id)
        .order_by(LedgerAccount.account_type, LedgerAccount.name)
        .all()
    )
    return accounts


@router.get(
    "/ledger/entries",
    response_model=List[LedgerEntryResponse],
    summary="List the authenticated user's ledger entries",
)
def list_ledger_entries(
    transaction_id: Optional[uuid.UUID] = Query(None, description="Filter by transaction ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[LedgerEntry]:
    """Return ledger entries for the authenticated user, optionally filtered by transaction."""
    q = db.query(LedgerEntry).filter(LedgerEntry.user_id == current_user.id)
    if transaction_id:
        q = q.filter(LedgerEntry.transaction_id == transaction_id)
    return q.order_by(LedgerEntry.created_at.desc()).all()


@router.get(
    "/ledger/balance",
    response_model=LedgerBalanceResponse,
    summary="Return aggregate debit/credit balance for the authenticated user",
)
def get_ledger_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return total_debit, total_credit, difference and is_balanced for the user."""
    return ledger_validation_service.get_user_balance_summary(
        db=db,
        user_id=current_user.id,
    )


@router.get(
    "/ledger/transaction/{transaction_id}",
    response_model=List[LedgerEntryResponse],
    summary="Return all ledger entries for a specific transaction",
)
def get_transaction_ledger_entries(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[LedgerEntry]:
    """Return every debit and credit entry posted for the given transaction.

    Ownership is enforced: only the owning user may access their transaction's entries.
    """
    entries = (
        db.query(LedgerEntry)
        .filter(
            LedgerEntry.transaction_id == transaction_id,
            LedgerEntry.user_id == current_user.id,
        )
        .order_by(LedgerEntry.created_at)
        .all()
    )
    return entries


# ============================================================================
# Phase 10 – Financial Intelligence & Analytics Endpoints
# ============================================================================

@router.get(
    "/analytics/summary",
    response_model=AnalyticsSummaryResponse,
    summary="[Phase 10] Financial analytics summary (income, expenses, net cash flow)",
)
def get_analytics_summary(
    period: Optional[str] = Query(
        None,
        description=(
            "Preset period: current_month | previous_month | "
            "last_3_months | last_6_months | last_12_months"
        ),
    ),
    start_date: Optional[date] = Query(None, description="Custom period start date (UTC)"),
    end_date: Optional[date] = Query(None, description="Custom period end date (UTC)"),
    currency: Optional[str] = Query(None, description="Filter to a single ISO 4217 currency code"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryResponse:
    """Return income / expense / net-cash-flow / savings-rate grouped by currency.

    Results are NEVER aggregated across currencies (multi-currency safety).
    Savings rate is null when income is zero.

    Phase 10 produces deterministic financial observations.
    It does not provide financial advice.
    """
    dr = _resolve_date_range(period, start_date, end_date)

    flow = financial_intelligence_service.calculate_net_cash_flow(
        db=db,
        user_id=current_user.id,
        start_date=dr.start,
        end_date=dr.end,
        currency=currency,
    )

    by_currency: List[AnalyticsSummaryByCurrency] = []
    for cur, data in flow.items():
        by_currency.append(
            AnalyticsSummaryByCurrency(
                currency=cur,
                total_income=data["total_income"],
                total_expenses=data["total_expenses"],
                net_cash_flow=data["net_cash_flow"],
                savings_rate=data["savings_rate"],
                income_transaction_count=data["income_transaction_count"],
                expense_transaction_count=data["expense_transaction_count"],
                transaction_count=data["transaction_count"],
            )
        )

    return AnalyticsSummaryResponse(
        period_start=dr.start,
        period_end=dr.end,
        by_currency=by_currency,
    )


@router.get(
    "/analytics/monthly",
    response_model=MonthlyAnalyticsResponse,
    summary="[Phase 10] Monthly income / expense / net cash flow breakdown",
)
def get_analytics_monthly(
    period: Optional[str] = Query(None, description="Preset period"),
    start_date: Optional[date] = Query(None, description="Custom period start date (UTC)"),
    end_date: Optional[date] = Query(None, description="Custom period end date (UTC)"),
    currency: Optional[str] = Query(None, description="Filter to a single ISO 4217 currency code"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonthlyAnalyticsResponse:
    """Return monthly income / expenses / net per currency in chronological order.

    Each row represents one calendar month for one currency.
    Results are never cross-currency aggregated.

    Phase 10 produces deterministic financial observations.
    It does not provide financial advice.
    """
    dr = _resolve_date_range(period, start_date, end_date)

    monthly_data = financial_intelligence_service.calculate_monthly_cash_flow(
        db=db,
        user_id=current_user.id,
        start_date=dr.start,
        end_date=dr.end,
        currency=currency,
    )

    items = [
        MonthlyDataByCurrency(
            year=row["year"],
            month=row["month"],
            currency=row["currency"],
            income=row["income"],
            expenses=row["expenses"],
            net_cash_flow=row["net_cash_flow"],
            income_transaction_count=row["income_transaction_count"],
            expense_transaction_count=row["expense_transaction_count"],
        )
        for row in monthly_data
    ]

    return MonthlyAnalyticsResponse(
        period_start=dr.start,
        period_end=dr.end,
        monthly_data=items,
    )


@router.get(
    "/analytics/categories",
    response_model=CategoryBreakdownResponse,
    summary="[Phase 10] Expense breakdown by category",
)
def get_analytics_categories(
    period: Optional[str] = Query(None, description="Preset period"),
    start_date: Optional[date] = Query(None, description="Custom period start date (UTC)"),
    end_date: Optional[date] = Query(None, description="Custom period end date (UTC)"),
    currency: Optional[str] = Query(None, description="Filter to a single ISO 4217 currency code"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryBreakdownResponse:
    """Return expense amounts by category with percentage of total, sorted descending.

    Missing/null categories are bucketed as 'Uncategorized'.
    Results are grouped by currency — no cross-currency aggregation.

    Phase 10 produces deterministic financial observations.
    It does not provide financial advice.
    """
    dr = _resolve_date_range(period, start_date, end_date)

    breakdown = financial_intelligence_service.calculate_expense_breakdown(
        db=db,
        user_id=current_user.id,
        start_date=dr.start,
        end_date=dr.end,
        currency=currency,
    )

    items: List[CategoryBreakdownItem] = []
    for cur, categories in breakdown.items():
        for cat_data in categories:
            items.append(
                CategoryBreakdownItem(
                    currency=cur,
                    category=cat_data["category"],
                    amount=cat_data["amount"],
                    transaction_count=cat_data["transaction_count"],
                    percentage=cat_data["percentage"],
                )
            )

    return CategoryBreakdownResponse(
        period_start=dr.start,
        period_end=dr.end,
        categories=items,
    )


@router.get(
    "/analytics/recurring",
    response_model=RecurringTransactionsResponse,
    summary="[Phase 10] Detected recurring expense patterns",
)
def get_analytics_recurring(
    currency: Optional[str] = Query(None, description="Filter to a single ISO 4217 currency code"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecurringTransactionsResponse:
    """Return detected recurring expense transaction patterns.

    Detection requires ≥ 3 occurrences of the same merchant with a similar amount.
    This is a detected pattern analysis, NOT a confirmed recurring charge list.

    Phase 10 produces deterministic financial observations.
    It does not provide financial advice.
    """
    patterns = financial_intelligence_service.detect_recurring_transactions(
        db=db,
        user_id=current_user.id,
        currency=currency,
    )

    items = [
        RecurringTransactionItem(
            currency=p["currency"],
            merchant=p["merchant"],
            approximate_amount=p["approximate_amount"],
            occurrence_count=p["occurrence_count"],
            detected_frequency=p["detected_frequency"],
            last_occurrence=p["last_occurrence"],
            average_days_between=p["average_days_between"],
        )
        for p in patterns
    ]

    return RecurringTransactionsResponse(detected_patterns=items)


@router.get(
    "/insights",
    response_model=InsightsListResponse,
    summary="[Phase 10] Structured financial insights",
)
def get_financial_insights(
    period: Optional[str] = Query(None, description="Preset period for insight generation"),
    start_date: Optional[date] = Query(None, description="Custom period start date (UTC)"),
    end_date: Optional[date] = Query(None, description="Custom period end date (UTC)"),
    generate: bool = Query(
        False,
        description=(
            "If true, generate new insights for this period before returning results. "
            "If false, return previously stored insights."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InsightsListResponse:
    """Return structured financial insights for the authenticated user.

    Insights are factual, deterministic observations derived from transaction data.
    They do NOT constitute financial advice.

    Set generate=true to compute new insights for the requested period.
    Set generate=false (default) to retrieve previously stored insights.

    Phase 10 produces deterministic financial observations.
    It does not provide financial advice.
    """
    dr = _resolve_date_range(period, start_date, end_date)

    if generate:
        insight_service.generate_summary_insights(
            db=db,
            user_id=current_user.id,
            start_date=dr.start,
            end_date=dr.end,
        )
        db.commit()

    insights = insight_service.get_insights(
        db=db,
        user_id=current_user.id,
        start_date=dr.start,
        end_date=dr.end,
    )

    return InsightsListResponse(
        period_start=dr.start,
        period_end=dr.end,
        insights=[FinancialInsightResponse.model_validate(i) for i in insights],
        total_count=len(insights),
    )


# ============================================================================
# Phase 11 – Financial Scenario Simulation
# ============================================================================

@router.post(
    "/scenarios/simulate",
    response_model=ScenarioSimulateResponse,
    status_code=200,
    summary="[Phase 11] Simulate a financial scenario",
    tags=["financial"],
)
def simulate_scenario(
    request: ScenarioSimulateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScenarioSimulateResponse:
    """Run a deterministic financial scenario simulation.

    Scenario simulation is deterministic mathematical analysis based on
    the authenticated user's historical transaction data.
    It is **NOT financial advice**.

    **This endpoint:**
    - Requires authentication (session cookie).
    - Uses ONLY the authenticated user's own transactions.
    - Never modifies any transaction, ledger entry, or financial event.
    - Never creates fake transactions.
    - Never performs cross-currency aggregation.
    - Is entirely stateless (no scenario is persisted to the database).

    **Scenario types:**
    - `EXPENSE_PERCENT_CHANGE`: Apply a % change to baseline expenses.
      Positive value = increase (e.g. 10 → +10%), negative = decrease.
    - `INCOME_PERCENT_CHANGE`: Apply a % change to baseline income.
    - `ADD_MONTHLY_EXPENSE`: Add a flat monthly amount to expenses.
    - `REMOVE_MONTHLY_EXPENSE`: Subtract a flat monthly amount from expenses.
    - `SAVINGS_TARGET`: Given a target savings amount, calculate the
      maximum allowable monthly expenses.

    **Period selection** (priority: start_date+end_date > period > current_month):
    - `period`: One of `current_month`, `previous_month`, `last_30_days`,
      `last_3_months`, `last_6_months`, `last_12_months`.
    - `start_date` + `end_date`: Custom date range.
    """
    # Resolve the date range (reuses Phase 10 helpers)
    dr = _resolve_date_range(
        period=request.period,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    # user_id comes ONLY from the authenticated session — never from request body
    return scenario_simulation_service.simulate(
        db=db,
        user_id=current_user.id,
        request=request,
        period_start=dr.start,
        period_end=dr.end,
    )


# ============================================================================
# Phase 12 – Financial Decision Support Engine
# ============================================================================

@router.post(
    "/decision-support/analyze",
    response_model=DecisionAnalyzeResponse,
    status_code=200,
    summary="[Phase 12] Analyze a hypothetical financial scenario",
    tags=["financial"],
)
def analyze_decision_support(
    request: DecisionAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DecisionAnalyzeResponse:
    """Evaluate a hypothetical financial scenario deterministically and explainably.

    This endpoint produces structured decision support results based on historical
    transaction state, account liquidity data, and explicit financial rules.

    **Engineering Invariants:**
    - Requires session authentication (`get_current_user`).
    - Strictly scoped to the authenticated user (prevents IDOR).
    - Preserves strict currency isolation (never aggregates across currencies).
    - Entirely stateless & read-only (no financial records or scenarios are modified or persisted).
    - Uses Python `Decimal` for all arithmetic.
    - Does NOT provide personalized financial or investment advice.
    - The final decision always remains with the user.
    """
    dr = _resolve_date_range(
        period=request.period,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    return decision_support_engine.analyze(
        db=db,
        user_id=current_user.id,
        request=request,
        period_start=dr.start,
        period_end=dr.end,
    )


# ============================================================================
# Phase 13 – LLM / AI Explanation Layer Endpoint
# ============================================================================

@router.post(
    "/decision-support/explain",
    response_model=DecisionExplainResponse,
    status_code=200,
    summary="[Phase 13] Explain a hypothetical financial scenario using AI",
    tags=["financial"],
)
async def explain_decision_support(
    request: DecisionExplainRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DecisionExplainResponse:
    """Evaluate a hypothetical financial scenario deterministically and explain it with AI.

    This endpoint first runs the deterministic Phase 12 DecisionSupportEngine evaluation.
    Then, it uses the configured LLM provider to translate the deterministic facts into
    an explainable, validated natural-language narrative.

    **Engineering Invariants:**
    - Requires session authentication (`get_current_user`).
    - Strictly scoped to the authenticated user (prevents IDOR).
    - Preserves strict currency isolation.
    - Entirely stateless & read-only.
    - All mathematical facts come from the deterministic backend.
    - Falls back gracefully without AI narrative if LLM is disabled or fails.
    - Does NOT provide personalized financial or investment advice.
    - The final decision always remains with the user.
    """
    dr = _resolve_date_range(
        period=request.period,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    return await ai_explanation_service.explain(
        db=db,
        user_id=current_user.id,
        request=request,
        period_start=dr.start,
        period_end=dr.end,
    )


# ============================================================================
# Phase 15 – Conversational AI Chat
# ============================================================================

@router.post(
    "/decision-support/chat",
    response_model=DecisionChatResponse,
    status_code=200,
    summary="[Phase 15] Chat about a financial decision analysis",
    tags=["financial"],
)
async def chat_decision_support(
    request: DecisionChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DecisionChatResponse:
    """Handle a conversational follow-up question about a decision analysis.

    The chat is specifically for understanding the current financial decision.
    It is NOT a general-purpose chatbot.

    **Engineering Invariants:**
    - Requires session authentication (`get_current_user`).
    - Strictly scoped to the authenticated user (prevents IDOR).
    - Backend controls all financial context supplied to Gemini.
    - Gemini does NOT directly query databases or financial tables.
    - Gemini does NOT execute financial actions.
    - Deterministic result remains the source of truth.
    - Graceful fallback if LLM is unavailable.
    """
    dr = _resolve_date_range(
        period=request.decision_context.period,
        start_date=request.decision_context.start_date,
        end_date=request.decision_context.end_date,
    )

    result = await ai_explanation_service.chat(
        db=db,
        user_id=current_user.id,
        decision_context=request.decision_context,
        question=request.question,
        conversation_history=request.conversation_history,
        period_start=dr.start,
        period_end=dr.end,
    )

    return DecisionChatResponse(
        answer=result["answer"],
        ai_status=result["ai_status"],
        ai_status_message=result["ai_status_message"],
    )

