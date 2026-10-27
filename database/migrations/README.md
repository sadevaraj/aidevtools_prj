# Database migrations

Alembic migrations for the PostgreSQL schema live in
`migrations/versions/`. `alembic.ini` points at this directory. The backend
startup command runs `python -m app.migrate` before Uvicorn becomes ready;
running it again is safe. A failed schema operation stops backend startup.

The first migration creates players with a case-insensitive username index,
database-backed revocable sessions that store only token hashes, the three
seeded puzzles, and games with a database-enforced unique `(player_id,
puzzle_id)` pair. Do not apply migrations manually to the developer database
for ordinary startup or tests.

Migration `0002_alert_incidents` adds the disabled-by-default development
alert outbox. It stores only a hashed incident identifier and bounded dispatch
state/expiry metadata; it never stores the Grafana payload or authentication
material. Expired records are pruned on accepted intake and cannot be dispatched
after their TTL. A durable run ID, attempt number, and claim timestamp permit
one authenticated GitHub Actions run to consume an eligible incident; the
claim is rejected for fabricated IDs, mismatched caller-supplied expiry,
replays, and expired incidents. The feature remains off unless the owner
privately configures the alert receiver and dispatch credentials.
