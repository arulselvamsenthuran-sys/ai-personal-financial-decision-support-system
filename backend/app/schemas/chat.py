"""Pydantic schemas for Phase 15: Conversational Financial AI Chat.

Provides data contracts for the decision-support chat endpoint.
The chat is specifically for understanding the current financial decision —
it is NOT a general-purpose chatbot.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.decision import DecisionAnalyzeRequest


class ChatMessage(BaseModel):
    """A single message in the conversation history."""

    role: str = Field(
        ...,
        description="Message role: 'user' or 'assistant'.",
    )
    content: str = Field(
        ...,
        max_length=2000,
        description="Message content.",
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'.")
        return v


class DecisionChatRequest(BaseModel):
    """Request model for POST /api/financial/decision-support/chat.

    Contains the decision context (reuses DecisionAnalyzeRequest fields),
    the user's question, and optional conversation history.
    """

    # Decision context — reuse the same fields
    decision_context: DecisionAnalyzeRequest = Field(
        ...,
        description="The decision-support scenario context for the current conversation.",
    )

    question: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="The user's follow-up question about the decision analysis.",
    )

    conversation_history: List[ChatMessage] = Field(
        default_factory=list,
        max_length=20,
        description="Previous conversation messages (limited to 20 for token safety).",
    )


class DecisionChatResponse(BaseModel):
    """Response model for the chat endpoint."""

    answer: str = Field(
        description="AI-generated answer to the user's question, or fallback message.",
    )
    ai_status: str = Field(
        description="Status of the AI response: 'success', 'fallback_disabled', 'fallback_provider_error', 'fallback_timeout'.",
    )
    ai_status_message: str = Field(
        description="Human-readable status message.",
    )
    disclaimer: str = Field(
        default=(
            "This AI chat translates deterministic mathematical calculations into natural language. "
            "It does not provide financial or investment advice. The deterministic backend is the sole source of truth."
        ),
        description="Standard AI decision support disclaimer.",
    )
