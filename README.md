# Simple Sudoku

Simple Sudoku is a full-stack desktop Sudoku application. Players create an
account, choose one of three verified easy puzzles, save progress manually, and
resume their own game later. FastAPI persists accounts and games in PostgreSQL;
React serves the browser experience through a same-origin API proxy.

## Try the development app

Open [Simple Sudoku on Render](https://simple-sudoku-frontend.onrender.com/).
Use a desktop browser, register your own account, then log in with the same
username and password when returning. There is no shared demo account.
Passwords cannot be recovered, so use a unique test password that you do not
use elsewhere. Choose one of the three puzzles and select **Save progress**
to persist your entries; changes are not saved automatically.

On 2026-10-27, both the [hosted frontend API health check](https://simple-sudoku-frontend.onrender.com/api/health)
and [backend health check](https://simple-sudoku-backend.onrender.com/api/health)
returned HTTP 200 with `{"status":"ok"}`. The [pipeline run](https://github.com/sadevaraj/aidevtools_prj/actions/runs/40416450021)
successfully published the paired images tagged
`87938670ba11da9b036233b803e712f81efe3378`, but its Render deploy job was
skipped; this tag is therefore not confirmed as deployed. The full browser
journey, backend-restart persistence check, and deployment/rollback verification
remain outstanding under [issue #13](https://github.com/sadevaraj/aidevtools_prj/issues/13).
Health-check success and published images alone do not establish full deployment
verification. See the [Render deployment runbook](docs/runbooks/render-development.md).

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

With `APP_ENV=development`, the backend can use an existing valid PostgreSQL
`DATABASE_URL` without the split `DATABASE_HOST`, `DATABASE_PORT`,
`DATABASE_NAME`, `DATABASE_USER`, and `DATABASE_PASSWORD` settings. The
backend's shared database engine uses that URL for startup, health checks, and
Alembic migrations. The Compose stack above continues to use split settings.
For an HTTPS development endpoint, set `COOKIE_SECURE=true` explicitly;
production still requires a valid `DATABASE_URL` and defaults to Secure
cookies.

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
cookies. HTTPS upstreams use the backend Host/SNI and verified system-CA TLS;
local HTTP upstreams remain supported. See the runbook's
[proxy health diagnosis](docs/runbooks/render-development.md#https-upstream-routing-and-health-diagnosis).
PostgreSQL is not published to the host; the `sudoku-prod-data` volume
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

The initial owner-approved sequence is:

1. Build and test the production images locally under
   [issue #16](https://github.com/sadevaraj/aidevtools_prj/issues/16).
2. The owner manually publishes the paired SHA-tagged images to GHCR and
   manually creates/configures the dedicated Sudoku Render PostgreSQL database
   and frontend/backend services. See the
   [Render development runbook](docs/runbooks/render-development.md).
3. Agents independently verify the deployed development service and rollback
   under [issue #13](https://github.com/sadevaraj/aidevtools_prj/issues/13).
4. Under the [subsequent approval](https://github.com/sadevaraj/aidevtools_prj/issues/12#issuecomment-6428965305),
   pipeline **implementation** may precede #13. CI-gated publication and
   disabled-by-default Render development CD are now configured under
   [issue #12](https://github.com/sadevaraj/aidevtools_prj/issues/12).
   Successful deployed verification under #13 remains mandatory before the owner
   enables CD. No workflow execution or remote success is claimed here.

The [pipeline runbook](docs/runbooks/pipeline.md) documents PR/main tests,
main paired SHA/digest publication with `GITHUB_TOKEN` (plus the default-off,
exact #20 demo-recovery exception), exact-image Render
deployment, owner variables/environment secret setup, failure notifications,
and operator fallback. Both CD flags default off; no Render credentials are
available to this implementation. GitHub Actions failure notifications require
the owner's account preferences; they are not log alerting or autonomous repair.

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

Issue #17 implements an opt-in authenticated HTTPS OTLP path for traces, metrics,
and logs using standard OpenTelemetry endpoint/header variables. It is not
enabled by default: the local HTTP traces/logs and gRPC metrics configuration
remains the default. No Render settings or credentials have been applied and no
remote Grafana ingestion or correlation has been verified. See the
[Render OTLP setup and verification runbook](docs/runbooks/render-development.md#optional-grafana-cloud-otlp-export)
for owner-operated configuration steps. User-impact alerts and automatic
recovery are not part of issue #15. Issue #18 adds a separately approved,
Grafana Cloud-managed save-5xx alert configuration; see the
[alert configuration notes](observability/grafana-cloud-alert/README.md).

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
build using Dockerized Node. It also runs production nginx HTTP/HTTPS proxy
regressions against isolated local fixtures, including Host/SNI routing,
certificate trust/name rejection, cookie/CSRF/trace forwarding, and failure
responses. Those tests use Docker and the same host `openssl` prerequisite as
local setup; they generate and remove disposable local TLS material, without
contacting Render. Run only that focused suite with
`sh scripts/test-frontend-proxy.sh`.
Backend tests also validate the pipeline YAML and exercise deployment success,
authorization/target gates, exact digest checks, API failures, partial deployment
and bounded polling with offline mocks; these tests never mutate Render.
The root command exits nonzero on any failed suite and removes
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
Local observability is available as the opt-in stack above, and issue #17 adds
optional authenticated HTTPS OTLP exporter support. Deployment and CI/CD remain
separate scope. The owner must configure the Grafana Cloud endpoint and private
Render backend variables, then verify remote ingestion; no remote setup or
correlation is claimed. Alerts and runtime automatic recovery are not
implemented or claimed by issue #15.

The [delivery process](docs/process.md), [agent team](.github/agents/README.md),
and [shared specification guard](.github/agents/guards/specification-changes.md)
describe how issues, DEV evidence, independent QA, and review are handled.

## Approved alert-to-Copilot development demo

The current approved scope is tracked by
[issue #20](https://github.com/sadevaraj/aidevtools_prj/issues/20), extending
the bounded receiver/repair implementation in
[issue #19](https://github.com/sadevaraj/aidevtools_prj/issues/19) and the
broader alert path in [issue #18](https://github.com/sadevaraj/aidevtools_prj/issues/18).
Issue #18's current body includes the authenticated receiver and bounded
repair-PR path; earlier notification-only notes in the repository are stale.

The #20 approval permits only a future owner-operated one-demo exception:
healthy trusted revision `T`, exact one-line `body.board` → `body.borad` fault
revision `F` on `demo/save-recovery`, verified rollback image pair, development
targets, immutable image provenance, and explicit test-window confirmation.
Ordinary CI remains unchanged and is expected to fail on `F`; its tests are not
weakened. A separate gated workflow validates the exact delta, builds unprivileged
images, exercises an authenticated save failure/unchanged database board on
disposable PostgreSQL, and only then exposes registry/deployment credentials to
trusted publication steps. The existing backend receiver binds an accepted
incident to durable `T`/`F`, branch, image digests, fixed Render targets, expiry,
and one OIDC-authenticated run/attempt claim. Alert payloads do not select
commands, refs, URLs, or permissions.

The main-ref repair workflow uses trusted `T` tooling and regression tests while
the candidate operates only on the exact `F` checkout. It accepts only the
single typo correction. Candidate/test jobs have no database, Render, or PR
publication credentials. Separate current-candidate QA and Reviewer Copilot
sessions must return distinct, patch-hash-bound PASS evidence before an isolated
publisher can open a PR based on the still-unchanged `F` demo branch. The owner
manually merges without squash/rebase/fast-forward directly onto F. The normal demo-branch pipeline then runs the full configured
suite and can publish/deploy only the owner-enabled exact repaired tree and
immutable image pair. Main remains healthy; merge is never automatic and
development CD requires explicit owner enablement for the expected repair.
No production service or completed-game data is a target.

Every feature and remote capability remains default-off. No live alert, Copilot
provider request, Actions run, GHCR publication, Render deployment, rollback, or
recovery was executed for this implementation. The user reports corrective
deployment and login/save verification, but independent issue #13 verification,
healthy rollback-pair evidence, missing PR credential, demo enablement, and
Copilot entitlement/quota remain unverified. Issues #12 and #13 are open; do not
enable or run the demo until the concrete prerequisites in
[the owner-operated runbook](docs/runbooks/development-save-demo.md) are met.

Course brief:
https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project
