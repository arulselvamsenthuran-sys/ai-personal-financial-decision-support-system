"""Phase 17: Conversation System — conversations and conversation_messages tables

Creates persistent storage for AI Financial Assistant conversations:
- conversations: Thread-level metadata with user ownership
- conversation_messages: Individual messages within a conversation

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-10-06 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create conversations and conversation_messages tables."""

    # -- conversations table --
    op.create_table(
        'conversations',
        sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            'title',
            sa.String(length=255),
            nullable=True,
            comment='Optional user-facing title for the conversation.',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'], unique=False)
    op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'], unique=False)

    # -- conversation_messages table --
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('conversation_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            'sequence_number',
            sa.Integer(),
            nullable=False,
            comment='Monotonically increasing message order within the conversation.',
        ),
        sa.Column(
            'role',
            sa.String(length=20),
            nullable=False,
            comment="Message role: 'user' or 'assistant'.",
        ),
        sa.Column(
            'content',
            sa.Text(),
            nullable=False,
            comment='Message content text.',
        ),
        sa.Column(
            'ai_status',
            sa.String(length=50),
            nullable=True,
            comment='AI response status (success, fallback_*, blocked_safety_violation).',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['conversation_id'],
            ['conversations.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversation_messages_conversation_id', 'conversation_messages', ['conversation_id'], unique=False)
    op.create_index('ix_conversation_messages_conv_seq', 'conversation_messages', ['conversation_id', 'sequence_number'], unique=False)


def downgrade() -> None:
    """Drop conversation_messages and conversations tables."""
    op.drop_index('ix_conversation_messages_conv_seq', table_name='conversation_messages')
    op.drop_index('ix_conversation_messages_conversation_id', table_name='conversation_messages')
    op.drop_table('conversation_messages')
    op.drop_index('ix_conversations_user_updated', table_name='conversations')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_table('conversations')
