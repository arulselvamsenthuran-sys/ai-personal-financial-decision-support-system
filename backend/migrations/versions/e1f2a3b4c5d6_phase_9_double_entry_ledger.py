"""Phase 9: Double-Entry Financial Ledger Engine

Creates ledger_accounts and ledger_entries tables.

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0123456
Create Date: 2026-09-20 11:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd8e9f0123456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ledger_accounts table
    op.create_table(
        'ledger_accounts',
        sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('financial_account_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('account_type', sa.String(length=20), nullable=False,
                  comment='One of: ASSET, LIABILITY, INCOME, EXPENSE, EQUITY'),
        sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['financial_account_id'], ['financial_accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'name', 'account_type',
            name='uq_ledger_account_user_name_type',
        ),
    )
    op.create_index('ix_ledger_accounts_user_id', 'ledger_accounts', ['user_id'], unique=False)
    op.create_index(
        'ix_ledger_accounts_financial_account_id',
        'ledger_accounts', ['financial_account_id'], unique=False,
    )

    # 2. Create ledger_entries table
    op.create_table(
        'ledger_entries',
        sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('ledger_account_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('transaction_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('financial_event_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('debit_amount', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('credit_amount', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['financial_event_id'], ['financial_events.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['ledger_account_id'], ['ledger_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ledger_entries_user_id', 'ledger_entries', ['user_id'], unique=False)
    op.create_index(
        'ix_ledger_entries_ledger_account_id',
        'ledger_entries', ['ledger_account_id'], unique=False,
    )
    op.create_index(
        'ix_ledger_entries_transaction_id',
        'ledger_entries', ['transaction_id'], unique=False,
    )
    op.create_index(
        'ix_ledger_entries_financial_event_id',
        'ledger_entries', ['financial_event_id'], unique=False,
    )


def downgrade() -> None:
    # Drop ledger_entries first (child)
    op.drop_index('ix_ledger_entries_financial_event_id', table_name='ledger_entries')
    op.drop_index('ix_ledger_entries_transaction_id', table_name='ledger_entries')
    op.drop_index('ix_ledger_entries_ledger_account_id', table_name='ledger_entries')
    op.drop_index('ix_ledger_entries_user_id', table_name='ledger_entries')
    op.drop_table('ledger_entries')

    # Then drop ledger_accounts (parent)
    op.drop_index('ix_ledger_accounts_financial_account_id', table_name='ledger_accounts')
    op.drop_index('ix_ledger_accounts_user_id', table_name='ledger_accounts')
    op.drop_table('ledger_accounts')
