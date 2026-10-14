"""User ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
import uuid

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.background_job import BackgroundJob
    from app.models.financial_account import FinancialAccount
    from app.models.financial_document import FinancialDocument
    from app.models.oauth import OAuthAccount
    from app.models.profile import UserProfile
    from app.models.session import Session


class User(Base):
    """Core identity model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
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
    profile: Mapped[Optional["UserProfile"]] = relationship(
        "UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[List["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    oauth_accounts: Mapped[List["OAuthAccount"]] = relationship(
        "OAuthAccount", back_populates="user", cascade="all, delete-orphan"
    )
    financial_accounts: Mapped[List["FinancialAccount"]] = relationship(
        "FinancialAccount", back_populates="user", cascade="all, delete-orphan"
    )
    financial_documents: Mapped[List["FinancialDocument"]] = relationship(
        "FinancialDocument", back_populates="user", cascade="all, delete-orphan", overlaps="documents,financial_account"
    )
    background_jobs: Mapped[List["BackgroundJob"]] = relationship(
        "BackgroundJob", back_populates="user", cascade="all, delete-orphan"
    )  # Phase 19
