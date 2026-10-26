"""Create persistent accounts, sessions, puzzles, and games."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_core_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(14), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("uq_players_username_ci", "players", [sa.text("lower(username)")], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "puzzles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(80), nullable=False, unique=True),
        sa.Column("clues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("solution", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("puzzle_id", sa.Integer(), sa.ForeignKey("puzzles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("board", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("player_id", "puzzle_id", name="uq_games_player_puzzle"),
    )


def downgrade() -> None:
    op.drop_table("games")
    op.drop_table("puzzles")
    op.drop_table("auth_sessions")
    op.drop_index("uq_players_username_ci", table_name="players")
    op.drop_table("players")
