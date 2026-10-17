"""Phase 21: Job deduplication and active job constraint.

Adds dedup_hash column to background_jobs table with a partial unique index
enforcing duplicate-prevention on active (QUEUED, RUNNING) jobs.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-15 15:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add dedup_hash column and unique partial index on active background jobs."""
    bind = op.get_bind()

    # 1. Add dedup_hash column
    bind.execute(sa.text("""
        ALTER TABLE background_jobs
        ADD COLUMN IF NOT EXISTS dedup_hash VARCHAR(64);
    """))

    # 2. Backfill existing jobs with hash of normalized parameters
    bind.execute(sa.text("""
        UPDATE background_jobs
        SET dedup_hash = encode(sha256(COALESCE(parameters::text, '{}')::bytea), 'hex')
        WHERE dedup_hash IS NULL;
    """))

    # 3. Reconcile pre-existing duplicate active jobs so index creation succeeds safely
    # (Keeps the newest job active and marks older active duplicates as FAILED with audit reason)
    bind.execute(sa.text("""
        WITH ranked_active_jobs AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, job_type, dedup_hash
                       ORDER BY created_at DESC
                   ) AS rn
            FROM background_jobs
            WHERE status IN ('QUEUED', 'RUNNING')
        )
        UPDATE background_jobs
        SET status = 'FAILED',
            error_message = 'Duplicate active job resolved during Phase 21 migration.',
            completed_at = NOW()
        WHERE id IN (
            SELECT id FROM ranked_active_jobs WHERE rn > 1
        );
    """))

    # 4. Create unique partial index on (user_id, job_type, dedup_hash) for active jobs
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_background_jobs_active_dedup
        ON background_jobs (user_id, job_type, dedup_hash)
        WHERE status IN ('QUEUED', 'RUNNING');
    """))


def downgrade() -> None:
    """Drop partial unique index and dedup_hash column."""
    bind = op.get_bind()
    bind.execute(sa.text("""
        DROP INDEX IF EXISTS ix_background_jobs_active_dedup;
    """))
    bind.execute(sa.text("""
        ALTER TABLE background_jobs
        DROP COLUMN IF EXISTS dedup_hash;
    """))
