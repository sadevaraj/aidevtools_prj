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

## Run production images locally

This separate smoke stack builds and runs the production frontend/backend image
targets with a project-isolated local PostgreSQL database; it does not contact
Render or GHCR. Generate fresh disposable values only in the command's process
environment (they are not written to `.env` or echoed), then run from the
repository root:

```sh
POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
SESSION_SECRET="$(openssl rand -hex 32)" \
docker compose -p sudoku-issue16-smoke -f compose.prod.yaml up --build --detach
```

Open `http://localhost:18080` (or set `PROD_FRONTEND_PORT` to another free host
port). The backend runs as `APP_ENV=production`, applies migrations and seeds
before listening, and uses the required `DATABASE_URL`. `COOKIE_SECURE=false`
is set only in this local HTTP Compose service; the app defaults to Secure
cookies in production and the Render runbook requires them enabled over HTTPS.
The frontend proxies same-origin `/api/` requests, preserving CSRF headers and
cookies. PostgreSQL is not published to the host; the `sudoku-prod-data` volume
persists local test accounts and games. Stop with
`docker compose -p sudoku-issue16-smoke -f compose.prod.yaml down --volumes
--remove-orphans` when the smoke test is finished; this removes only the
explicitly named smoke project's containers, network, and disposable database
volume. Re-run that cleanup command even after a failed browser check. Compose
still needs its required variables interpolated for `down`, so use harmless
throwaway placeholders (not the generated values):

```sh
POSTGRES_PASSWORD=cleanup SESSION_SECRET=cleanup \
docker compose -p sudoku-issue16-smoke -f compose.prod.yaml down --volumes --remove-orphans
```

For the production-image browser journey, register and log in, confirm the
selector contains exactly three puzzles, start a puzzle, enter a value and
manually save it, then restart only the backend with
`docker restart sudoku-issue16-smoke-backend-1`. Resume the puzzle and
confirm the saved value remains. Complete the puzzle with a valid solution and
confirm the completed board is read-only, log out, then use a separate account
to verify it cannot see the first account's game. These are manual local checks;
record actual results rather than inferring them from image builds.
Use only disposable test accounts. Sign out of each account; then remove the
smoke project and its database volume with the cleanup command above.

For the owner-operated manual registry/deployment steps, exact Render service
settings, and rollback procedure, see
[the development Render runbook](docs/runbooks/render-development.md). No GHCR
push, Render provisioning, or deployment is performed by this local workflow.

The paired SHA image builder is:

```sh
sh scripts/build-images.sh [optional-extra-tag]
```

It builds `ghcr.io/sadevaraj/simple-sudoku-backend:<full-HEAD-SHA>` and
`ghcr.io/sadevaraj/simple-sudoku-frontend:<full-HEAD-SHA>`, optionally adding the
same extra tag to both, and prints local image IDs plus manual push commands.
Build and publish only from a clean, reviewed revision: on a dirty worktree the
script warns that the SHA tag describes HEAD, not the uncommitted image contents.
The script does not log in or push.

## Delivery order

The owner-approved sequence is:

1. Build and test the production images locally under
   [issue #16](https://github.com/sadevaraj/aidevtools_prj/issues/16).
2. The owner manually publishes the paired SHA-tagged images to GHCR and
   manually creates/configures the dedicated Sudoku Render PostgreSQL database
   and frontend/backend services. See the
   [Render development runbook](docs/runbooks/render-development.md).
3. Agents independently verify the deployed development service and rollback
   under [issue #13](https://github.com/sadevaraj/aidevtools_prj/issues/13).
4. Only after #13, implement CI-gated image publication under
   [issue #12](https://github.com/sadevaraj/aidevtools_prj/issues/12).

Production deployment is deferred. Local tests, image builds, and any CI checks
do not by themselves establish a successful GHCR publication or Render
deployment.

## Local observability

Issue #15 adds an opt-in local-only OpenTelemetry stack. Add a unique
`GRAFANA_ADMIN_PASSWORD` to the ignored `.env` before starting it; the default
Grafana user is `admin`. Do not reuse deployment or shared credentials. The
observability services use their own Compose project, network, and persistent
volumes and can start without the application:

```sh
docker compose -p sudoku-observability -f compose.observability.yaml up -d
```

Then start the app on the shared telemetry network (the sample ports avoid the
usual local defaults):

```sh
FRONTEND_PORT=15173 docker compose -p sudoku-app -f compose.yaml \
  -f compose.observability-app.yaml up --build
```

Open the Sudoku app at `http://localhost:15173` and Grafana at
`http://localhost:13000` (sign in with the local Grafana credentials). The
provisioned **Simple Sudoku — Local Observability** dashboard shows request
rate, server-error rate, p95 latency, and save outcomes. Expected validation,
authentication, and other 4xx rejections are separate from server errors.
Prometheus is bound to localhost at `http://localhost:19090`; its remote-write
ingestion endpoint, Loki, Tempo, and the Collector accept traffic only on the
private Docker network. The Collector forwards metrics to Prometheus with trace
exemplars enabled. Grafana anonymous access is disabled.

To follow a save manually, sign in and save progress, then allow several seconds for the periodic metric export and Collector forwarding. Open Grafana Explore →
Tempo and search for service `sudoku-api` and operation
`PUT /api/games/{game_id}`. Open the trace and its `db.save_game` child span. Use
the trace-to-logs link (span time padded by one minute on each side and
filtered by trace ID) to find the structured `http_request` event with the same
trace ID and `outcome=success`. In the dashboard, inspect the matching save
outcome and click its exemplar to open the correlated trace. For independent QA,
capture the dashboard, trace with its database child span, and the correlated
log as Grafana UI evidence. Requests are intentionally metadata-only; no board
or credential values are recorded.

Stop only these local services, retaining telemetry volumes, with:

```sh
docker compose -p sudoku-app -f compose.yaml -f compose.observability-app.yaml down
docker compose -p sudoku-observability -f compose.observability.yaml down
```

Local telemetry does not establish telemetry collection from Render. A secure
remote destination, network reachability, retention, and budget remain
unresolved; no remote correlation is configured or claimed. User-impact alerts
and automatic recovery are not part of issue #15 and are not implemented here.

## Developer verification

Run the single root unit + real-PostgreSQL integration command:

```sh
sh scripts/test.sh
```

It first requires the observability directory and Grafana datasource file and
validates bounded trace-to-logs time padding with trace-ID filtering; missing or
invalid configuration fails before Docker starts. It then builds the backend test
image, starts PostgreSQL in an isolated temporary
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
Local observability is available as the opt-in stack above. Deployment and
CI/CD are separate scope; secure remote Render telemetry destination,
reachability, retention, and budget remain unresolved. Alerts and runtime
automatic recovery are not implemented or claimed by issue #15.

The [delivery process](docs/process.md), [agent team](.github/agents/README.md),
and [shared specification guard](.github/agents/guards/specification-changes.md)
describe how issues, DEV evidence, independent QA, and review are handled.

Course brief:
https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project
