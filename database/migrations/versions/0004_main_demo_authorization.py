"""Use MAIN for new demo authorizations; preserve historical rows and chain."""

from alembic import op
import sqlalchemy as sa

revision = "0004_main_demo"
down_revision = "0003_demo_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT VALID retains historical branch-based rows without relabelling them
    # as approved MAIN authorizations. Runtime rejects them; new writes require
    # main. No account/game data or existing 0002/0003 migration is changed.
    op.drop_constraint(
        "ck_demo_authorization_branch", "development_demo_authorizations", type_="check",
    )
    op.execute(
        "ALTER TABLE development_demo_authorizations ADD CONSTRAINT "
        "ck_demo_authorization_branch CHECK (branch = 'main') NOT VALID"
    )
    op.create_index(
        "uq_demo_main_fault", "development_demo_authorizations", ["fault_revision"],
        unique=True, postgresql_where=sa.text("branch = 'main'"),
    )


def downgrade() -> None:
    op.drop_index("uq_demo_main_fault", table_name="development_demo_authorizations")
    op.drop_constraint(
        "ck_demo_authorization_branch", "development_demo_authorizations", type_="check",
    )
    op.execute(
        "ALTER TABLE development_demo_authorizations ADD CONSTRAINT "
        "ck_demo_authorization_branch CHECK (branch = 'demo/save-recovery') NOT VALID"
    )
