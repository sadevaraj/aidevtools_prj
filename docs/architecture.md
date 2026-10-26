# Application Architecture

## Agreed Decisions

- `frontend/`: React, TypeScript, and Vite, with a desktop dark theme.
- `backend/`: Python and FastAPI.
- `database/`: database migrations, initialization/seed assets, and three verified
  easy puzzles. Do not store credentials or live database files in Git.
- PostgreSQL for persistent data.
- A new, dedicated Render PostgreSQL instance for Sudoku development, separate
  from Kanban storage. A separate external provider such as Neon is not selected.
- Separate frontend and backend Docker images and separate Render Web Services
  deploying those images, following the existing Kanban project's image-based
  approach. The frontend is not deployed as a Render Static Site in this design.
- The frontend image serves the built static assets through a web server.
- Render uses free default addresses; no custom domain is available.
- Development environment only for the initial delivery, with separate frontend
  and backend Render Web Services. Production is deferred.

## Containers and Local Startup

Provide a Dockerfile for each application service and Docker Compose for the full
local system: frontend, backend, and PostgreSQL.

The intended startup command from the repository root is:

```sh
docker compose up --build
```

The local setup must not depend on an external hosted database or manual SQL
steps. Compose must coordinate database readiness, migrations, and idempotent
puzzle seeding before the API becomes ready. PostgreSQL uses a named volume so
ordinary container recreation preserves saved games. Document first-run setup
and any required configuration without committing secrets.

`compose.prod.yaml` is the production-image smoke stack: it builds the runtime
frontend/backend images, starts them with PostgreSQL, and publishes only the
frontend on host port 18080 by default. Run `docker compose -f compose.prod.yaml
up --build`; use `PROD_FRONTEND_PORT` if that port is occupied. It sets
`APP_ENV=production` but explicitly disables Secure cookies for this local
HTTP-only smoke environment. Render must retain Secure cookies over HTTPS.

The frontend Nginx container serves the built React assets and proxies
same-origin `/api/` requests to `API_UPSTREAM`. In Compose this is
`http://backend:8000`; a future Render frontend service must receive the backend
service address as a runtime value. The browser does not call a separate API
origin, so the flow does not depend on cross-site cookies or permissive CORS.
Nginx listens on `PORT` (80 locally; Render's configured service port remotely).
The API is reachable only from the Compose network locally; PostgreSQL is not
published on a host port.

## Render Deployment

Build versioned frontend and backend images and publish them to a container
registry. Render pulls the selected images rather than rebuilding the application
from source. GitHub Container Registry (GHCR) is the selected registry for both
images; the packages are public so Render does not need registry credentials.

Use Render PostgreSQL for the deployed system. Local Compose includes
its own PostgreSQL container; deploying that container on Render's ephemeral
filesystem is not a substitute for managed persistent storage.

The owner-approved delivery order in issue #11 is: build and verify images locally
(issue #16); the owner manually pushes the public GHCR image pair and manually
configures Render; agents verify deployed behavior and rollback in issue #13;
CI-gated image publication is deferred to issue #12. No GHCR push, Render
provisioning, or deployment is part of local development evidence. All published
and deployed versions must identify the exact paired image tags.

## Initial Development Deployment

- Provide two application Web Services: development frontend and backend.
- Use development configuration, deployment credentials, session secrets, and
  game/account data. Never use Kanban production data or credentials.
- Provision a new Render PostgreSQL instance dedicated to Sudoku. Never point
  Sudoku migrations or seed scripts at Kanban's database.
- The owner manually pushes the tested image pair to public GHCR and configures
  two Render Web Services to pull the exact image tags. Set the backend database
  to the new Sudoku database's Internal Database URL; set the frontend's
  `API_UPSTREAM` to the backend's internal service address.
- CI-gated publication and any automated deployment are deferred to issue #12.
- Record immutable image references for the deployed frontend/backend pair.
- Verify development after deployment, including
  login, puzzle loading, save/resume, and the expected deployed version.
- Retain the last verified image pair for rollback. Check database migration
  compatibility before rollback; image rollback does not undo database changes.
- Any controlled failure demonstration must be restricted to development.

### Deferred Production Environment

Production services and manual promotion are not part of the initial delivery.
If introduced later, isolate production data, credentials, and configuration and
promote the exact verified development image pair without rebuilding.
The higher-scoring CI/CD rubric target of dev deployment plus manual production
deployment is deferred; do not claim it is implemented.

## Test Entry Point

The repository-root command is `sh scripts/test.sh`. It runs backend rules,
configuration, security/API, migrations and persistence tests against a fresh
real PostgreSQL container, plus frontend interaction tests, TypeScript checks,
and a production Vite build. The test database is tmpfs-backed in a unique test
Compose project and is never the named developer application volume. Any setup,
migration, seed, test, frontend, or build failure propagates as a nonzero command
result. See `compose.test.yaml` and `docs/adr/0001-core-implementation-decisions.md`.

- Backend unit tests: Sudoku rules, validation, and relevant authentication logic.
- Frontend unit/component tests: board interactions and user-visible states.
- Integration tests: API, real PostgreSQL persistence/migrations, authentication,
  ownership, save/resume, and completion rules.
- Integration infrastructure must be started and cleaned up by the test tooling,
  without deleting the developer's application database volume.
- Configuration tests cover Render `PORT`, missing/invalid production
  `DATABASE_URL`, production Secure-cookie defaults and the local HTTP override.
  Real-PostgreSQL tests cover idempotent migrations/seeds and API behavior.

Local test and Compose results are development evidence only; they do not
demonstrate remote CI, Render configuration, or deployment success.

## Observability

The owner approved logs, metrics, and traces using the Kanban project's approach
on 26 October 2026. This is implementation scope, not a completed capability.

- Use OpenTelemetry instrumentation and an OpenTelemetry Collector.
- Provide a separate local observability Compose stack with Prometheus (metrics),
  Loki (structured logs), Tempo (traces), and Grafana (correlated viewing).
- Persist telemetry in appropriate volumes and provision Grafana data sources and
  a Sudoku dashboard. Local observability endpoints must not be exposed publicly
  with anonymous access.
- Instrument saving a game as the key user journey, including API handling and
  database work. Propagate trace context through the frontend reverse proxy.
- Emit structured logs with trace/span IDs, service name, environment, version,
  operation, and outcome. Record latency and request outcomes with bounded labels.
- Link metrics to traces using exemplars where supported and traces to logs using
  trace IDs. Do not use per-request trace IDs as metric labels.
- Show request/error rates, latency, and save success/failure metrics in Grafana.
  Distinguish expected validation/authentication rejections from server failures.
- Exclude usernames, passwords, password hashes, session/CSRF tokens, cookies,
  database credentials, request bodies, and saved board contents from telemetry.
- Verify a save request can be followed across stored traces and structured logs,
  with its outcome represented in metrics and correlation viewable in Grafana.
  Test redaction and exporter failure handling; telemetry outages must not make
  successful saves fail, and exporter errors must be visible diagnostically.

The local stack does not prove telemetry from Render is collected. Agree on a
secure, reachable destination, retention, and budget before remote telemetry
configuration. Do not expose the local anonymous stack to receive internet traffic.
User-impact alerts and bounded automatic remediation are also approved scope,
as described below.

### Local observability run and evidence (implementation note)

The independent local stack is `compose.observability.yaml`; the application opt-in overlay is `compose.observability-app.yaml`. Set a private `GRAFANA_ADMIN_PASSWORD` in the ignored `.env`, then start the observability project before the application overlay so the shared private network exists. See the README local observability section for the exact commands, localhost UI addresses, shutdown steps, and Grafana correlation procedure. The observability stack has persistent Prometheus, Loki, Tempo, and Grafana volumes; Grafana anonymous access is disabled and host-published interfaces are bound to localhost. The Collector OTLP receivers and Prometheus remote-write ingestion are private-network only; Prometheus exemplar storage is enabled for metric-to-trace links.

The provisioned dashboard distinguishes expected 4xx rejections from server errors and shows request rate, latency, and save outcomes. Request labels use method, route template, status class, and finite outcome values; trace IDs never become metric labels. Trace context is created for manual save requests, passed by the frontend Nginx proxy, and continued by the API and database save span. Structured logs are metadata-only and correlate by trace ID. Follow the README procedure to inspect the dashboard, trace, database child span, correlated log, and the metric exemplar link; capture independent UI evidence during QA.

These are local-only results. They do not establish Render telemetry collection. A secure remote destination, reachability, retention, and budget remain unresolved and require an explicit decision before remote telemetry is configured or any deployed correlation is claimed. Issue #15 does not implement alerts or automatic recovery.

## User-Impact Alerts and Automatic Recovery

The owner requested alerting and fixing alongside observability on 26 October
2026, using Kanban as the intended reference. The exact Kanban alert/fix mechanism
has not been verified in the inspected local files; do not claim it is reused or
implemented until its source/configuration is identified.

- Alert on failure of a real user journey, initially saving game progress, using
  the instrumented outcomes rather than CPU usage or a static health response.
- Exclude expected invalid-input and authorization rejections from service-outage
  counts. Define a measurable threshold, evaluation window, and no-data behaviour
  before implementation, accounting for Render free-service cold starts.
- Deliver alerts to a responder and record an incident with relevant sanitized
  evidence. Group duplicate alerts and limit notifications/actions to prevent storms.
- An alert wakes a runtime on-call agent, separate from the development agents.
  It investigates evidence and may perform only an explicitly allow-listed
  recovery action for a recognized failure in Sudoku development.
- Select and approve one concrete fault/recovery pair before implementing tools.
  Candidate actions such as restarting a service or rolling back an image are not
  automatically authorized by this plan and must fit Render's available APIs,
  permissions, and database compatibility constraints.
- Never expose arbitrary shell execution, database resets, credential changes,
  generated code deployment, or access to Kanban/production to the responder.
- Use finite attempts, action cooldowns, scoped credentials, and an auditable
  timeline. Unknown failures, exhausted attempts, or ineligible actions stop
  automation and explicitly request operator attention.
- Verify the selected real user journey after recovery, using isolated synthetic
  Sudoku data where necessary. A tool returning success is not proof of recovery.
  Keep incidents unresolved if verification fails; never loop indefinitely.
- Provide a safe, documented development-only failure trigger for the agreed
  scenario and demonstrate alert -> agent -> permitted action -> verified recovery.
- Test alert rules, deduplication, action eligibility, attempt limits, tool errors,
  and verification failures. Record actual end-to-end evidence, not simulated
  claims of a remote fix.

This approves the capability, not arbitrary remediation actions, new paid
services, or deployment of unreviewed changes. Notification destination, runtime
model/tool implementation, trigger hosting, and the exact recovery scenario still
require design agreement. A recorded human recovery alone does not demonstrate
the alert-triggered agent criterion.

## Remaining Operational Decisions and Follow-up

- Render PostgreSQL provisioning: confirm the workspace has a free database slot
  available before creation. Current documented limits are one active Free
  Postgres database per workspace, 1 GB storage, expiry after 30 days, and no
  managed backups. An existing free Kanban database may prevent another free
  instance in the same workspace; do not delete or modify Kanban to make room.
  The owner selected a new dedicated free Sudoku database in issue #11; the owner
  still needs to confirm availability, choose a common region, and plan a manual
  export before the 30-day expiry.
- Issue #11 does not select a compute plan for the two Render Web Services.
  Confirm the owner's plan/budget choice before provisioning. Render's Free Web
  Services cannot receive private-network requests, which affects the frontend
  proxy's `API_UPSTREAM`; use the backend's public HTTPS URL if its selected plan
  cannot receive private traffic. The browser still accesses the frontend
  same-origin proxy. See the Render runbook for the decision and source links.
- The frontend reverse proxy and its runtime `API_UPSTREAM` setting are
  implemented. Issue #13 must verify the deployed same-origin cookie/CSRF flow.
- Exact CI triggers and automated publication/deployment mechanics are deferred
  to issue #12. The owner performs initial GHCR publication and Render setup.
- Secure telemetry destination for Render, retention, and hosting/free-tier limits.
- Alert thresholds/no-data policy, notification and responder hosting, runtime
  model access/cost if needed, and one approved fault/recovery scenario with
  verification and scoped permissions.
