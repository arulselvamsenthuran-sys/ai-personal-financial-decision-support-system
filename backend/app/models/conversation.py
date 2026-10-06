"""Phase 17: Conversation and ConversationMessage ORM models.

Persistent storage for AI Financial Assistant conversations.
Each conversation is strictly owned by a single user (IDOR protection).
Messages are ordered by sequence number within a conversation.
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Conversation(Base):
    """A conversation thread between the user and the AI Financial Assistant.

    Security invariant: user_id is always derived from the authenticated session,
    never from user/LLM input.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_id", "user_id"),
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional user-facing title for the conversation.",
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
    user: Mapped["User"] = relationship("User")
    messages: Mapped[List["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.sequence_number",
    )


class ConversationMessage(Base):
    """A single message within a conversation.

    Messages are ordered by sequence_number (monotonically increasing within a conversation).
    Role is either 'user' or 'assistant'.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_conversation_id", "conversation_id"),
        Index(
            "ix_conversation_messages_conv_seq",
            "conversation_id",
            "sequence_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Monotonically increasing message order within the conversation.",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Message role: 'user' or 'assistant'.",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Message content text.",
    )
    ai_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="AI response status (success, fallback_*, blocked_safety_violation).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
