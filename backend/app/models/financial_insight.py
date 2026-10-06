"""Financial Insight ORM model — Phase 10.

Stores system-generated, deterministic financial observations.
These are factual metric-based observations, NOT financial advice.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional
import uuid

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class FinancialInsight(Base):
    """A system-generated deterministic financial observation.

    Phase 10 produces factual, metric-based observations from transaction data.
    It does NOT produce financial advice, recommendations, or predictions.

    Insight types (insight_type values):
        HIGH_EXPENSE_CATEGORY      – A single category exceeds a configured threshold of total expenses.
        EXPENSE_INCREASE           – A category's spending increased significantly vs the prior period.
        NEGATIVE_CASH_FLOW         – Expenses exceeded income in the analysis period.
        RECURRING_EXPENSE_DETECTED – A merchant/amount pattern was detected recurring monthly.
        INCOME_DECREASE            – Income decreased significantly vs the prior period.
        LARGE_TRANSACTION          – A single transaction is significantly above the user's average.

    Severity values: INFO | WARNING | ALERT
        INFO    – neutral observation, no action implied.
        WARNING – noteworthy pattern worth reviewing.
        ALERT   – significant deviation (e.g. expenses > income).
    """

    __tablename__ = "financial_insights"
    __table_args__ = (
        Index("ix_financial_insights_user_id", "user_id"),
        Index("ix_financial_insights_user_type", "user_id", "insight_type"),
        Index("ix_financial_insights_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Categorical classification of the insight
    insight_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment=(
            "One of: HIGH_EXPENSE_CATEGORY, EXPENSE_INCREASE, NEGATIVE_CASH_FLOW, "
            "RECURRING_EXPENSE_DETECTED, INCOME_DECREASE, LARGE_TRANSACTION"
        ),
    )

    # Severity: INFO | WARNING | ALERT
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="INFO",
        comment="One of: INFO, WARNING, ALERT",
    )

    # Human-readable factual title (no advice language)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Factual description of the observed metric
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # The primary numeric metric that triggered this insight (e.g. 50.00 for 50% increase)
    metric_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )

    # ISO 4217 currency code associated with this insight
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    # The date range that was analysed to generate this insight
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Additional structured metadata (e.g. category name, merchant, amounts)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
