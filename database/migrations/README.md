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
