"""Immutable Financial Event ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.financial_account import FinancialAccount
    from app.models.transaction import Transaction
    from app.models.user import User


class FinancialEvent(Base):
    """Immutable financial event ledger entry."""

    __tablename__ = "financial_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_financial_events_idempotency_key"),
        Index("ix_financial_events_user_account", "user_id", "financial_account_id"),
        Index("ix_financial_events_transaction_id", "transaction_id"),
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
        ForeignKey("financial_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), default="system", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User")
    financial_account: Mapped["FinancialAccount"] = relationship("FinancialAccount")
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")


# Enforce Immutability via SQLAlchemy ORM events
@event.listens_for(FinancialEvent, "before_update")
def _prevent_financial_event_update(mapper, connection, target):
    raise RuntimeError("FinancialEvent records are immutable and cannot be updated.")


@event.listens_for(FinancialEvent, "before_delete")
def _prevent_financial_event_delete(mapper, connection, target):
    raise RuntimeError("FinancialEvent records are immutable and cannot be deleted.")
