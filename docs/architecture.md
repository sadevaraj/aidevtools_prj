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

## Render Deployment

Build versioned frontend and backend images and publish them to a container
registry. Render pulls the selected images rather than rebuilding the application
from source. GitHub Container Registry (GHCR) is the selected registry for both
images; registry permissions and pipeline configuration remain to be established.

Use Render PostgreSQL for the deployed system. Local Compose includes
its own PostgreSQL container; deploying that container on Render's ephemeral
filesystem is not a substitute for managed persistent storage.

CI must test the revision before publishing/deploying its images. Deployment and
rollback must identify the exact image versions. Image publication, remote
configuration, and deployment still require the applicable authorization/access.

## Initial Development Deployment

- Provide two application Web Services: development frontend and backend.
- Use development configuration, deployment credentials, session secrets, and
  game/account data. Never use Kanban production data or credentials.
- Provision a new Render PostgreSQL instance dedicated to Sudoku. Never point
  Sudoku migrations or seed scripts at Kanban's database.
- Run CI tests before building the frontend/backend image pair for a revision.
  Automatically deploy successful builds to development.
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

Provide one documented repository-root command that runs both unit and integration
tests and exits unsuccessfully if any required suite fails. The exact command will
be established with the project tooling.

- Backend unit tests: Sudoku rules, validation, and relevant authentication logic.
- Frontend unit/component tests: board interactions and user-visible states.
- Integration tests: API, real PostgreSQL persistence/migrations, authentication,
  ownership, save/resume, and completion rules.
- Integration infrastructure must be started and cleaned up by the test tooling,
  without deleting the developer's application database volume.

These are implementation requirements, not claims that tests or containers exist
or pass yet.

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

## Details to Resolve Before Implementation

- Render PostgreSQL provisioning: confirm the workspace has a free database slot
  available before creation. Current documented limits are one active Free
  Postgres database per workspace, 1 GB storage, expiry after 30 days, and no
  managed backups. An existing free Kanban database may prevent another free
  instance in the same workspace; do not delete or modify Kanban to make room.
  Resolve availability/cost with the owner and plan a manual export before expiry.
- Frontend-to-API routing: investigate a same-origin reverse proxy in the frontend
  container to avoid reliance on third-party cookies across Render addresses.
  Preserve HttpOnly session cookies and CSRF protection; verify the deployed flow.
- Registry permissions, capacity/cost for two Render Web Services and the database
  arrangement, exact CI triggers, deployment mechanics, and rollback checks.
- Exact test runner entry point and authentication libraries/rate limits.
- Secure telemetry destination for Render, retention, and hosting/free-tier limits.
- Alert thresholds/no-data policy, notification and responder hosting, runtime
  model access/cost if needed, and one approved fault/recovery scenario with
  verification and scoped permissions.
