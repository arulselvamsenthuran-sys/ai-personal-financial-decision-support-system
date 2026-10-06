"""Financial transaction ORM model."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Text, UniqueConstraint, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.services.fingerprint import generate_transaction_fingerprint

if TYPE_CHECKING:
    from app.models.financial_account import FinancialAccount
    from app.models.user import User


class Transaction(Base):
    """Normalized financial transaction model."""

    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_account_date", "financial_account_id", "transaction_date"),
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
        UniqueConstraint(
            "financial_account_id",
            "transaction_fingerprint",
            name="uq_account_transaction_fingerprint",
        ),
        ForeignKeyConstraint(
            ["financial_account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            ondelete="CASCADE",
        ),
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
    financial_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        index=True,
        nullable=False,
    )
    transaction_fingerprint: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    transaction_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    merchant: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="posted", server_default="posted", nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(50), default="manual", server_default="manual", nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", overlaps="transactions,financial_account")
    financial_account: Mapped["FinancialAccount"] = relationship(
        "FinancialAccount", back_populates="transactions", overlaps="user"
    )


@event.listens_for(Transaction, "before_insert")
def _auto_generate_transaction_fingerprint(mapper, connection, target):
    if not target.transaction_fingerprint:
        target.transaction_fingerprint = generate_transaction_fingerprint(
            financial_account_id=target.financial_account_id,
            transaction_date=target.transaction_date,
            amount=target.amount,
            transaction_type=target.transaction_type,
            merchant=target.merchant,
            reference=target.reference,
        )
