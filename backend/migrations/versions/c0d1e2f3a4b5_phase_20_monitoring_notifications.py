"""Phase 20: Scheduled Monitoring & In-App Notifications.

Creates:
  - monitoring_schedules table (recurring schedule configurations)
  - notifications table (user in-app notification inbox)

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-10-15 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create monitoring_schedules and notifications tables."""
    bind = op.get_bind()

    # ------------------------------------------------------------------ #
    # Enum: monitoring frequency
    # ------------------------------------------------------------------ #
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE monitoring_frequency_enum AS ENUM ('DAILY', 'WEEKLY');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # ------------------------------------------------------------------ #
    # monitoring_schedules
    # ------------------------------------------------------------------ #
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS monitoring_schedules (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name          VARCHAR(200) NOT NULL,
            frequency     monitoring_frequency_enum NOT NULL,
            day_of_week   SMALLINT,
            hour_of_day   SMALLINT NOT NULL DEFAULT 8,
            is_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_run_at   TIMESTAMPTZ,
            next_run_at   TIMESTAMPTZ
        );
    """))

    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_monitoring_schedules_user_id "
        "ON monitoring_schedules (user_id);"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_monitoring_schedules_next_run "
        "ON monitoring_schedules (next_run_at);"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_monitoring_schedules_user_enabled "
        "ON monitoring_schedules (user_id, is_enabled);"
    ))

    # ------------------------------------------------------------------ #
    # notifications
    # ------------------------------------------------------------------ #
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS notifications (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            schedule_id       UUID REFERENCES monitoring_schedules(id) ON DELETE SET NULL,
            notification_type VARCHAR(50) NOT NULL DEFAULT 'INSIGHT_GENERATED',
            title             VARCHAR(255) NOT NULL,
            body              TEXT NOT NULL,
            is_read           BOOLEAN NOT NULL DEFAULT FALSE,
            read_at           TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))

    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_id "
        "ON notifications (user_id);"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_read "
        "ON notifications (user_id, is_read);"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_created "
        "ON notifications (user_id, created_at);"
    ))


def downgrade() -> None:
    """Drop monitoring_schedules and notifications tables and enums."""
    bind = op.get_bind()
    bind.execute(sa.text("DROP TABLE IF EXISTS notifications CASCADE;"))
    bind.execute(sa.text("DROP TABLE IF EXISTS monitoring_schedules CASCADE;"))
    bind.execute(sa.text("DROP TYPE IF EXISTS monitoring_frequency_enum;"))
