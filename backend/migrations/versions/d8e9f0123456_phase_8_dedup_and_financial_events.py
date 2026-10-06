"""Phase 8: Transaction Deduplication and Immutable Financial Event System

Revision ID: d8e9f0123456
Revises: 9f85920ef197
Create Date: 2026-09-18 19:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.services.fingerprint import generate_transaction_fingerprint

# revision identifiers, used by Alembic.
revision: str = 'd8e9f0123456'
down_revision: Union[str, None] = '9f85920ef197'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create financial_events table
    op.create_table(
        'financial_events',
        sa.Column('id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('financial_account_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('transaction_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('source', sa.String(length=50), server_default='system', nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['financial_account_id'], ['financial_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_financial_events_idempotency_key')
    )
    op.create_index('ix_financial_events_transaction_id', 'financial_events', ['transaction_id'], unique=False)
    op.create_index('ix_financial_events_user_account', 'financial_events', ['user_id', 'financial_account_id'], unique=False)
    op.create_index(op.f('ix_financial_events_user_id'), 'financial_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_financial_events_financial_account_id'), 'financial_events', ['financial_account_id'], unique=False)

    # 2. Add transaction_fingerprint column (nullable initially for safe backfill)
    op.add_column('transactions', sa.Column('transaction_fingerprint', sa.String(length=64), nullable=True))

    # 3. Backfill fingerprints for existing transactions
    conn = op.get_bind()
    res = conn.execute(sa.text(
        "SELECT id, financial_account_id, transaction_date, amount, transaction_type, merchant, reference FROM transactions"
    )).fetchall()

    seen_account_fingerprints = set()
    for row in res:
        tx_id, account_id, tx_date, amount, tx_type, merchant, ref = row
        fingerprint = generate_transaction_fingerprint(
            financial_account_id=account_id,
            transaction_date=tx_date,
            amount=amount,
            transaction_type=tx_type,
            merchant=merchant,
            reference=ref,
        )

        # Handle historical duplicate edge cases safely to preserve data and satisfy unique constraint
        key = (account_id, fingerprint)
        if key in seen_account_fingerprints:
            # If historical data contains duplicate rows, make fingerprint unique for migration
            import uuid
            fingerprint = generate_transaction_fingerprint(
                financial_account_id=account_id,
                transaction_date=tx_date,
                amount=amount,
                transaction_type=tx_type,
                merchant=merchant,
                reference=f"{ref or ''}_legacy_{uuid.uuid4().hex[:8]}",
            )
        seen_account_fingerprints.add((account_id, fingerprint))

        conn.execute(
            sa.text("UPDATE transactions SET transaction_fingerprint = :fp WHERE id = :id"),
            {"fp": fingerprint, "id": tx_id}
        )

    # 4. Make transaction_fingerprint NOT NULL and create index/unique constraint
    op.alter_column('transactions', 'transaction_fingerprint', nullable=False)
    op.create_index(op.f('ix_transactions_transaction_fingerprint'), 'transactions', ['transaction_fingerprint'], unique=False)
    op.create_unique_constraint('uq_account_transaction_fingerprint', 'transactions', ['financial_account_id', 'transaction_fingerprint'])


def downgrade() -> None:
    op.drop_constraint('uq_account_transaction_fingerprint', 'transactions', type_='unique')
    op.drop_index(op.f('ix_transactions_transaction_fingerprint'), table_name='transactions')
    op.drop_column('transactions', 'transaction_fingerprint')

    op.drop_index(op.f('ix_financial_events_financial_account_id'), table_name='financial_events')
    op.drop_index(op.f('ix_financial_events_user_id'), table_name='financial_events')
    op.drop_index('ix_financial_events_user_account', table_name='financial_events')
    op.drop_index('ix_financial_events_transaction_id', table_name='financial_events')
    op.drop_table('financial_events')
