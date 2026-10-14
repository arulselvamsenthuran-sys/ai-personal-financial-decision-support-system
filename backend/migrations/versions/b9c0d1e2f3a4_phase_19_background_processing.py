"""Phase 19: Background Processing System — background_jobs table.

Creates persistent storage for background processing job lifecycle tracking.

Revision ID: b9c0d1e2f3a4
Revises: a7b8c9d0e1f2
Create Date: 2026-10-14 22:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create background_jobs table, enums, and indexes using raw SQL."""
    bind = op.get_bind()

    # Create enum types idempotently via PL/pgSQL DO blocks
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE background_job_type_enum AS ENUM
                ('ANALYZE_TRANSACTIONS', 'GENERATE_INSIGHTS', 'DOCUMENT_REPROCESS', 'PORTFOLIO_RECALCULATION');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE background_job_status_enum AS ENUM
                ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # Create the table using raw SQL to avoid SQLAlchemy re-creating the enum types
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS background_jobs (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_type          background_job_type_enum NOT NULL,
            status            background_job_status_enum NOT NULL DEFAULT 'QUEUED',
            progress_pct      INTEGER NOT NULL DEFAULT 0,
            progress_message  VARCHAR(500),
            parameters        JSON,
            result_payload    JSON,
            error_message     TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at        TIMESTAMPTZ,
            completed_at      TIMESTAMPTZ
        );
    """))

    # Indexes
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_background_jobs_user_id ON background_jobs (user_id);"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_background_jobs_status ON background_jobs (status);"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_background_jobs_user_status ON background_jobs (user_id, status);"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_background_jobs_user_created ON background_jobs (user_id, created_at);"
    ))


def downgrade() -> None:
    """Drop background_jobs table and associated enums."""
    bind = op.get_bind()
    bind.execute(sa.text("DROP TABLE IF EXISTS background_jobs CASCADE;"))
    bind.execute(sa.text("DROP TYPE IF EXISTS background_job_status_enum;"))
    bind.execute(sa.text("DROP TYPE IF EXISTS background_job_type_enum;"))
