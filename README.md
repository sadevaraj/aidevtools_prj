# Simple Sudoku

Simple Sudoku is a full-stack desktop Sudoku application. Players create an
account, choose one of three verified easy puzzles, save progress manually, and
resume their own game later. FastAPI persists accounts and games in PostgreSQL;
React serves the browser experience through a same-origin API proxy.

## Product rules

The authoritative [product specification](docs/specs/product.md) defines
SUD-01 through SUD-14. The implementation preserves these core rules:

- Usernames are 1–14 ASCII letters, digits, or underscores and unique without
  regard to case. Passwords are 8–14 case-sensitive characters and are never
  trimmed, lowercased, or silently shortened. Passwords cannot be recovered.
- Each player has at most one persisted game per puzzle. Only the signed-in
  owner can list, read, save, or submit their games.
- The three predefined puzzles are migrated and seeded automatically. Original
  clues are immutable; API boards must be 9×9 and contain only digits 1–9 or
  blank cells.
- Entries are saved only when the player selects **Save progress**. Submission
  validation runs on the backend: incomplete, incorrect, and correct boards
  produce distinct outcomes. A correct completion is persisted and permanently
  read-only; completed games cannot be edited, reset, replayed, or restarted.
- No correctness feedback is given while entering digits. Log out on shared
  devices; closing a browser does not revoke a server session.

## Run locally with Docker Compose

Requirements: Docker with the Compose plugin and `openssl`. Node/npm are used
inside Docker only; they do not need to be installed on the host.

1. Copy `.env.example` to `.env`.
2. Set `POSTGRES_PASSWORD` to a new local-only value and `SESSION_SECRET` to a
   different random value of at least 32 characters (for example, generate
   values with `openssl rand -hex 24` and `openssl rand -hex 32`). Keep them in
   the ignored `.env`; never use deployment or shared credentials.
3. Start the full stack from the repository root:

   ```sh
   docker compose up --build
   ```

4. Open `http://localhost:5173`. If that host port is occupied, set
   `FRONTEND_PORT=15173` in `.env` and open `http://localhost:15173`.
   PostgreSQL and the API are not published to host ports; the frontend
   container proxies `/api/` to the backend on the Compose network.
5. Stop with `docker compose down`. The named PostgreSQL volume is retained
   across ordinary container recreation. **Do not use `docker compose down -v`
   unless you intentionally want to irreversibly delete the local database.**

Compose waits for PostgreSQL health, then the backend applies Alembic migrations
and validates/idempotently seeds exactly three puzzles before Uvicorn starts.
The API health check verifies a database query. Migration or seed failure stops
backend startup rather than reporting ready.

## Developer verification

Run the single root unit + real-PostgreSQL integration command:

```sh
sh scripts/test.sh
```

It builds the backend test image, starts PostgreSQL in an isolated temporary
Compose project using a tmpfs database, applies migrations/seeds, runs backend
tests, then runs frontend component tests and the production TypeScript/Vite
build using Dockerized Node. It exits nonzero on any failed suite and removes
only its own test containers/network. It never mounts or deletes the developer
application database volume.

The React app is tested with Vitest/Testing Library; backend behavior and
persistence are tested with Pytest against actual PostgreSQL. `npm audit` for
the locked frontend dependency tree currently reports no known vulnerabilities.
The developer checks do not represent remote CI or deployment verification.

## Implementation and delivery boundaries

The engineering choices and verification implications are recorded in
[ADR-0001](docs/adr/0001-core-implementation-decisions.md). The
[architecture](docs/architecture.md) covers the complete delivery plan.
Deployment, CI/CD, telemetry, alerts, and runtime recovery are separate scope
and are not claimed as implemented by this core milestone.

The [delivery process](docs/process.md), [agent team](.github/agents/README.md),
and [shared specification guard](.github/agents/guards/specification-changes.md)
describe how issues, DEV evidence, independent QA, and review are handled.

Course brief:
https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project
