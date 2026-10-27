"""Database models for accounts, revocable sessions, puzzles, and games."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (Index("uq_players_username_ci", text("lower(username)"), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(14), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Puzzle(Base):
    __tablename__ = "puzzles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    clues: Mapped[list[list[int | None]]] = mapped_column(JSONB, nullable=False)
    solution: Mapped[list[list[int]]] = mapped_column(JSONB, nullable=False)


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("player_id", "puzzle_id", name="uq_games_player_puzzle"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    puzzle_id: Mapped[int] = mapped_column(ForeignKey("puzzles.id", ondelete="RESTRICT"), nullable=False)
    board: Mapped[list[list[int | None]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertIncident(Base):
    """Sanitized, durable outbox entry for one accepted development alert."""

    __tablename__ = "alert_incidents"
    __table_args__ = (
        Index("ix_alert_incidents_dispatch", "status", "next_attempt_at"),
        Index("ix_alert_incidents_expiry", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error_code: Mapped[str | None] = mapped_column(String(40))
    execution_run_id: Mapped[int | None] = mapped_column(BigInteger)
    execution_run_attempt: Mapped[int | None] = mapped_column(Integer)
    execution_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demo_authorization_id: Mapped[str | None] = mapped_column(
        ForeignKey("development_demo_authorizations.id", ondelete="RESTRICT"),
        unique=True,
    )


class DevelopmentDemoAuthorization(Base):
    """Single-use, owner-armed save-recovery demonstration authorization."""

    __tablename__ = "development_demo_authorizations"
    __table_args__ = (
        CheckConstraint(
            "trusted_revision ~ '^[0-9a-f]{40}$' AND "
            "fault_revision ~ '^[0-9a-f]{40}$' AND "
            "expected_repaired_tree ~ '^[0-9a-f]{40}$'",
            name="ck_demo_authorization_revisions",
        ),
        CheckConstraint(
            "backend_digest ~ '^sha256:[0-9a-f]{64}$' AND "
            "frontend_digest ~ '^sha256:[0-9a-f]{64}$' AND "
            "rollback_backend_digest ~ '^sha256:[0-9a-f]{64}$' AND "
            "rollback_frontend_digest ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_demo_authorization_digests",
        ),
        CheckConstraint(
            "backend_target = 'https://simple-sudoku-backend.onrender.com' AND "
            "frontend_target = 'https://simple-sudoku-frontend.onrender.com'",
            name="ck_demo_authorization_targets",
        ),
        CheckConstraint(
            "branch = 'demo/save-recovery'",
            name="ck_demo_authorization_branch",
        ),
        CheckConstraint(
            "trusted_revision <> fault_revision AND "
            "backend_digest <> rollback_backend_digest AND "
            "frontend_digest <> rollback_frontend_digest",
            name="ck_demo_authorization_distinct",
        ),
        CheckConstraint(
            "state IN ('armed', 'claimed', 'revoked', 'expired')",
            name="ck_demo_authorization_state",
        ),
        CheckConstraint(
            "(claimed_run_id IS NULL AND claimed_run_attempt IS NULL AND claimed_at IS NULL) OR "
            "(claimed_run_id > 0 AND claimed_run_attempt > 0 AND claimed_at IS NOT NULL)",
            name="ck_demo_authorization_claim",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trusted_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    fault_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_repaired_tree: Mapped[str] = mapped_column(String(40), nullable=False)
    branch: Mapped[str] = mapped_column(String(80), nullable=False)
    backend_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    frontend_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    rollback_backend_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    rollback_frontend_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    backend_target: Mapped[str] = mapped_column(String(120), nullable=False)
    frontend_target: Mapped[str] = mapped_column(String(120), nullable=False)
    rollback_evidence_url: Mapped[str] = mapped_column(String(250), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="armed")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alert_incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("alert_incidents.id", ondelete="RESTRICT"), unique=True
    )
    claimed_run_id: Mapped[int | None] = mapped_column(BigInteger)
    claimed_run_attempt: Mapped[int | None] = mapped_column(Integer)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
