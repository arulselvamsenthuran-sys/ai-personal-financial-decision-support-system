"""Pydantic schemas for Phase 17: Conversation System.

Provides data contracts for persistent conversation management endpoints.
Each conversation is user-owned and stores ordered message history.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
import uuid

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Conversation Schemas
# ---------------------------------------------------------------------------

class ConversationCreateRequest(BaseModel):
    """Request body for creating a new conversation."""

    title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional user-facing title for the conversation.",
    )


class ConversationResponse(BaseModel):
    """Response model for a single conversation."""

    id: uuid.UUID = Field(description="Conversation ID.")
    title: Optional[str] = Field(description="Conversation title.")
    message_count: int = Field(description="Number of messages in this conversation.")
    created_at: datetime = Field(description="When the conversation was started.")
    updated_at: datetime = Field(description="When the conversation was last updated.")

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    """Response model for listing conversations."""

    conversations: List[ConversationResponse] = Field(
        description="List of conversations for the authenticated user."
    )
    total_count: int = Field(description="Total number of conversations.")


# ---------------------------------------------------------------------------
# Message Schemas
# ---------------------------------------------------------------------------

class MessageSendRequest(BaseModel):
    """Request body for sending a message in a conversation."""

    question: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="The user's question or message.",
    )
    message: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Alias for question.",
    )

    def get_text(self) -> str:
        text = self.question or self.message or ""
        return text.strip()


class MessageResponse(BaseModel):
    """Response model for a single conversation message."""

    id: uuid.UUID = Field(description="Message ID.")
    conversation_id: uuid.UUID = Field(description="Parent conversation ID.")
    sequence_number: int = Field(description="Message ordering within the conversation.")
    role: str = Field(description="Message role: 'user' or 'assistant'.")
    content: str = Field(description="Message content.")
    ai_status: Optional[str] = Field(description="AI response status for assistant messages.")
    created_at: datetime = Field(description="When this message was created.")

    model_config = {"from_attributes": True}


class MessageSendResponse(BaseModel):
    """Response model after sending a message (includes both user and assistant messages)."""

    user_message: MessageResponse = Field(
        description="The persisted user message."
    )
    assistant_message: MessageResponse = Field(
        description="The AI assistant's response message."
    )
    ai_status: str = Field(
        description="AI response status: 'success', 'fallback_*', 'blocked_safety_violation'.",
    )
    ai_status_message: str = Field(
        description="Human-readable AI status message.",
    )
    disclaimer: str = Field(
        default=(
            "This AI chat translates deterministic mathematical calculations into natural language. "
            "It does not provide financial or investment advice. The deterministic backend is the sole source of truth."
        ),
        description="Standard AI decision support disclaimer.",
    )


class ConversationHistoryResponse(BaseModel):
    """Response model for retrieving conversation message history."""

    conversation_id: uuid.UUID = Field(description="Conversation ID.")
    title: Optional[str] = Field(description="Conversation title.")
    messages: List[MessageResponse] = Field(
        description="Ordered list of messages in this conversation."
    )
    total_count: int = Field(description="Total number of messages.")
