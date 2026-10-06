"""Phase 10: Financial Intelligence Engine — financial_insights table

Creates the financial_insights table for storing system-generated,
deterministic financial observations.

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-09-23 07:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create financial_insights table with indexes."""
    op.create_table(
        'financial_insights',
        sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            'insight_type',
            sa.String(length=50),
            nullable=False,
            comment=(
                'One of: HIGH_EXPENSE_CATEGORY, EXPENSE_INCREASE, NEGATIVE_CASH_FLOW, '
                'RECURRING_EXPENSE_DETECTED, INCOME_DECREASE, LARGE_TRANSACTION'
            ),
        ),
        sa.Column(
            'severity',
            sa.String(length=20),
            nullable=False,
            comment='One of: INFO, WARNING, ALERT',
        ),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column(
            'metric_value',
            sa.Numeric(precision=18, scale=4),
            nullable=True,
            comment='Primary numeric metric that triggered this insight.',
        ),
        sa.Column(
            'currency',
            sa.String(length=3),
            nullable=True,
            comment='ISO 4217 currency code associated with this insight.',
        ),
        sa.Column(
            'period_start',
            sa.Date(),
            nullable=True,
            comment='Start of the date range analysed to generate this insight.',
        ),
        sa.Column(
            'period_end',
            sa.Date(),
            nullable=True,
            comment='End of the date range analysed to generate this insight.',
        ),
        sa.Column(
            'metadata_json',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Additional structured metadata (category, merchant, amounts, etc.).',
        ),
        sa.Column(
            'created_at',
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

    # Indexes for common query patterns
    op.create_index(
        'ix_financial_insights_user_id',
        'financial_insights',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        'ix_financial_insights_user_type',
        'financial_insights',
        ['user_id', 'insight_type'],
        unique=False,
    )
    op.create_index(
        'ix_financial_insights_created_at',
        'financial_insights',
        ['created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Drop financial_insights table and its indexes."""
    op.drop_index('ix_financial_insights_created_at', table_name='financial_insights')
    op.drop_index('ix_financial_insights_user_type', table_name='financial_insights')
    op.drop_index('ix_financial_insights_user_id', table_name='financial_insights')
    op.drop_table('financial_insights')
