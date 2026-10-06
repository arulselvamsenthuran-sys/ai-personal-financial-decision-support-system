"""Phase 17: Conversation System API routes.

Endpoints for managing persistent AI Financial Assistant conversations:
- POST   /api/conversations                          — Start a new conversation
- GET    /api/conversations                          — List user's conversations
- GET    /api/conversations/{conversation_id}        — Get conversation details & history
- DELETE /api/conversations/{conversation_id}        — Delete a conversation
- POST   /api/conversations/{conversation_id}/messages — Send a message

Security invariants:
- All endpoints require session authentication.
- AI endpoints enforce rate limiting (Phase 16).
- Conversation ownership is enforced at the service layer (IDOR protection).
- Prompt injection detection is applied per-request on the current question only.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.ai_safety import check_ai_rate_limit
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationHistoryResponse,
    ConversationListResponse,
    ConversationResponse,
    MessageResponse,
    MessageSendRequest,
    MessageSendResponse,
)
from app.services.conversation_service import conversation_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Conversation CRUD
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ConversationResponse,
    status_code=201,
    summary="[Phase 17] Start a new conversation",
)
def create_conversation(
    request_data: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    """Start a new conversation for the authenticated user.

    user_id is derived from the session — never from the request body.
    """
    conversation = conversation_service.create_conversation(
        db=db,
        user_id=current_user.id,
        title=request_data.title,
    )

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        message_count=0,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="[Phase 17] List user's conversations",
)
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationListResponse:
    """List all conversations for the authenticated user, most recent first."""
    conversations = conversation_service.list_conversations(
        db=db,
        user_id=current_user.id,
    )
    total = conversation_service.count_conversations(db=db, user_id=current_user.id)

    items = []
    for conv in conversations:
        msg_count = conversation_service.count_messages(db=db, conversation_id=conv.id)
        items.append(
            ConversationResponse(
                id=conv.id,
                title=conv.title,
                message_count=msg_count,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
            )
        )

    return ConversationListResponse(
        conversations=items,
        total_count=total,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationHistoryResponse,
    summary="[Phase 17] Get conversation with message history",
)
def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationHistoryResponse:
    """Retrieve a conversation and its message history.

    Enforces user ownership — returns 404 if not found or not owned.
    """
    conversation = conversation_service.get_conversation(
        db=db,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    messages = conversation_service.get_messages(
        db=db,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )

    return ConversationHistoryResponse(
        conversation_id=conversation.id,
        title=conversation.title,
        messages=[MessageResponse.model_validate(m) for m in messages],
        total_count=len(messages),
    )


@router.delete(
    "/{conversation_id}",
    status_code=204,
    summary="[Phase 17] Delete a conversation",
)
def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete a conversation and all its messages.

    Enforces user ownership — returns 404 if not found or not owned.
    """
    deleted = conversation_service.delete_conversation(
        db=db,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.post(
    "/{conversation_id}/messages",
    response_model=MessageSendResponse,
    status_code=201,
    summary="[Phase 17] Send a message in a conversation",
)
async def send_message(
    conversation_id: uuid.UUID,
    request_data: MessageSendRequest,
    req: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageSendResponse:
    """Send a message in a conversation and receive the AI assistant's response.

    Security invariants:
    - Requires session authentication.
    - Enforces AI rate limiting (Phase 16).
    - Conversation ownership enforced (IDOR protection).
    - Prompt injection detection on current question only (not on history).
    - Stored history is wrapped in XML trust boundaries before LLM context.
    - Graceful fallback if LLM is unavailable.
    """
    check_ai_rate_limit(request=req, user_id=current_user.id)

    result = await conversation_service.send_message(
        db=db,
        user_id=current_user.id,
        conversation_id=conversation_id,
        question=request_data.get_text(),
    )

    # Handle not-found case
    if "error" in result and result["error"] == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["detail"],
        )

    return MessageSendResponse(
        user_message=MessageResponse.model_validate(result["user_message"]),
        assistant_message=MessageResponse.model_validate(result["assistant_message"]),
        ai_status=result["ai_status"],
        ai_status_message=result["ai_status_message"],
    )
