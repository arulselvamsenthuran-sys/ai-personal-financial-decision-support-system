"""Double-Entry Ledger ORM models for Phase 9.

Implements the accounting equation: TOTAL DEBITS == TOTAL CREDITS

LedgerAccount  – chart-of-accounts entry (ASSET / LIABILITY / INCOME / EXPENSE / EQUITY)
LedgerEntry    – individual debit or credit posting against a LedgerAccount

Design rules enforced at the ORM level:
  - A LedgerEntry carries EITHER a debit_amount OR a credit_amount, never both, never neither.
  - Both amounts are stored as Decimal(18,4); negative values are rejected by the service layer.
  - LedgerEntry records are NOT immutable (unlike FinancialEvent) to allow ledger corrections,
    but in the current phase they are only written by the posting engine, never directly mutated.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.financial_account import FinancialAccount
    from app.models.financial_event import FinancialEvent
    from app.models.transaction import Transaction
    from app.models.user import User


# ---------------------------------------------------------------------------
# Account type enumeration
# ---------------------------------------------------------------------------
class AccountType(str, Enum):
    """Standard chart-of-accounts classification."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    EQUITY = "EQUITY"


# ---------------------------------------------------------------------------
# LedgerAccount – one row per logical account in the chart of accounts
# ---------------------------------------------------------------------------
class LedgerAccount(Base):
    """A named ledger account within the chart of accounts for a single user.

    Each user has their own isolated set of ledger accounts so that data from
    one user can never be accessed by another (no IDOR).
    """

    __tablename__ = "ledger_accounts"
    __table_args__ = (
        # Prevent users from accidentally creating duplicate named accounts
        UniqueConstraint(
            "user_id", "name", "account_type",
            name="uq_ledger_account_user_name_type",
        ),
        Index("ix_ledger_accounts_user_id", "user_id"),
        Index("ix_ledger_accounts_financial_account_id", "financial_account_id"),
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
    # Optional link to a FinancialAccount (e.g. "Bank Account" maps to a real bank account)
    financial_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="One of: ASSET, LIABILITY, INCOME, EXPENSE, EQUITY",
    )
    currency: Mapped[str] = mapped_column(
        String(3), default="USD", server_default="USD", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
    financial_account: Mapped[Optional["FinancialAccount"]] = relationship(
        "FinancialAccount"
    )
    entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry", back_populates="ledger_account", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# LedgerEntry – one debit or one credit posting
# ---------------------------------------------------------------------------
class LedgerEntry(Base):
    """A single debit or credit posting in the double-entry ledger.

    Invariants (enforced by ledger_service before insertion):
      - Exactly one of (debit_amount, credit_amount) is a positive Decimal > 0.
      - The other field is NULL (stored as None / SQL NULL).
      - Neither field may contain a negative value.

    This model is intentionally NOT decorated with immutability ORM events so
    that accounting corrections remain possible in future phases; however the
    current posting engine never mutates entries after creation.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("ix_ledger_entries_user_id", "user_id"),
        Index("ix_ledger_entries_ledger_account_id", "ledger_account_id"),
        Index("ix_ledger_entries_transaction_id", "transaction_id"),
        Index("ix_ledger_entries_financial_event_id", "financial_event_id"),
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
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ledger_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    financial_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("financial_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Exactly one of these will be non-NULL per entry (debit XOR credit)
    debit_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    credit_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=18, scale=4), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
    ledger_account: Mapped["LedgerAccount"] = relationship(
        "LedgerAccount", back_populates="entries"
    )
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")
    financial_event: Mapped[Optional["FinancialEvent"]] = relationship("FinancialEvent")
