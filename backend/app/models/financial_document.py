"""Financial document metadata ORM model."""

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional
import uuid

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.financial_account import FinancialAccount


class FinancialDocument(Base):
    """Metadata for uploaded financial documents."""

    __tablename__ = "financial_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["financial_account_id", "user_id"],
            ["financial_accounts.id", "financial_accounts.user_id"],
            ondelete="SET NULL",
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
    financial_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        index=True,
        nullable=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(50), default="bank_statement", server_default="bank_statement", nullable=False
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    storage_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(50),
        default="uploaded",
        server_default="uploaded",
        index=True,
        nullable=False,
    )
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    statement_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    statement_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    user: Mapped["User"] = relationship("User", back_populates="financial_documents", overlaps="documents,financial_account")
    financial_account: Mapped[Optional["FinancialAccount"]] = relationship(
        "FinancialAccount", back_populates="documents", overlaps="user"
    )
