"""Add a bounded, sanitized alert dispatch outbox."""

from alembic import op
import sqlalchemy as sa

revision = "0002_alert_incidents"
down_revision = "0001_core_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_incidents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=40), nullable=True),
        sa.Column("execution_run_id", sa.BigInteger(), nullable=True),
        sa.Column("execution_run_attempt", sa.Integer(), nullable=True),
        sa.Column("execution_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 3", name="ck_alert_incidents_attempts"),
        sa.CheckConstraint(
            "(execution_run_id IS NULL AND execution_run_attempt IS NULL AND "
            "execution_claimed_at IS NULL) OR "
            "(execution_run_id > 0 AND execution_run_attempt > 0 AND "
            "execution_claimed_at IS NOT NULL)",
            name="ck_alert_incidents_execution_claim",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatching', 'dispatched', 'retry', 'failed')",
            name="ck_alert_incidents_status",
        ),
    )
    op.create_index(
        "ix_alert_incidents_dispatch",
        "alert_incidents",
        ["status", "next_attempt_at"],
    )
    op.create_index("ix_alert_incidents_expiry", "alert_incidents", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_incidents_expiry", table_name="alert_incidents")
    op.drop_index("ix_alert_incidents_dispatch", table_name="alert_incidents")
    op.drop_table("alert_incidents")
