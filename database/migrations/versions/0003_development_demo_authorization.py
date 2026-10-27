"""Persist one owner-authorized development save-recovery demonstration."""

from alembic import op
import sqlalchemy as sa

revision = "0003_demo_authorization"
down_revision = "0002_alert_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "development_demo_authorizations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trusted_revision", sa.String(length=40), nullable=False),
        sa.Column("fault_revision", sa.String(length=40), nullable=False),
        sa.Column("expected_repaired_tree", sa.String(length=40), nullable=False),
        sa.Column("branch", sa.String(length=80), nullable=False),
        sa.Column("backend_digest", sa.String(length=71), nullable=False),
        sa.Column("frontend_digest", sa.String(length=71), nullable=False),
        sa.Column("rollback_backend_digest", sa.String(length=71), nullable=False),
        sa.Column("rollback_frontend_digest", sa.String(length=71), nullable=False),
        sa.Column("backend_target", sa.String(length=120), nullable=False),
        sa.Column("frontend_target", sa.String(length=120), nullable=False),
        sa.Column("rollback_evidence_url", sa.String(length=250), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="armed"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "alert_incident_id",
            sa.String(length=64),
            sa.ForeignKey("alert_incidents.id", ondelete="RESTRICT"),
            nullable=True,
            unique=True,
        ),
        sa.Column("claimed_run_id", sa.BigInteger(), nullable=True),
        sa.Column("claimed_run_attempt", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "trusted_revision ~ '^[0-9a-f]{40}$' AND "
            "fault_revision ~ '^[0-9a-f]{40}$' AND "
            "expected_repaired_tree ~ '^[0-9a-f]{40}$'",
            name="ck_demo_authorization_revisions",
        ),
        sa.CheckConstraint(
            "backend_digest ~ '^sha256:[0-9a-f]{64}$' AND "
            "frontend_digest ~ '^sha256:[0-9a-f]{64}$' AND "
            "rollback_backend_digest ~ '^sha256:[0-9a-f]{64}$' AND "
            "rollback_frontend_digest ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_demo_authorization_digests",
        ),
        sa.CheckConstraint(
            "backend_target = 'https://simple-sudoku-backend.onrender.com' AND "
            "frontend_target = 'https://simple-sudoku-frontend.onrender.com'",
            name="ck_demo_authorization_targets",
        ),
        sa.CheckConstraint("branch = 'demo/save-recovery'", name="ck_demo_authorization_branch"),
        sa.CheckConstraint(
            "trusted_revision <> fault_revision AND "
            "backend_digest <> rollback_backend_digest AND "
            "frontend_digest <> rollback_frontend_digest",
            name="ck_demo_authorization_distinct",
        ),
        sa.CheckConstraint(
            "state IN ('armed', 'claimed', 'revoked', 'expired')",
            name="ck_demo_authorization_state",
        ),
        sa.CheckConstraint(
            "(claimed_run_id IS NULL AND claimed_run_attempt IS NULL AND claimed_at IS NULL) OR "
            "(claimed_run_id > 0 AND claimed_run_attempt > 0 AND claimed_at IS NOT NULL)",
            name="ck_demo_authorization_claim",
        ),
    )
    op.create_index(
        "ix_demo_authorization_state_expiry",
        "development_demo_authorizations",
        ["state", "expires_at"],
    )
    op.add_column(
        "alert_incidents",
        sa.Column(
            "demo_authorization_id",
            sa.String(length=64),
            sa.ForeignKey("development_demo_authorizations.id", ondelete="RESTRICT"),
            nullable=True,
            unique=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("alert_incidents", "demo_authorization_id")
    op.drop_index(
        "ix_demo_authorization_state_expiry",
        table_name="development_demo_authorizations",
    )
    op.drop_table("development_demo_authorizations")
