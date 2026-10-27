# Manual Render development deployment

This runbook records the owner-operated sequence from issue
[#11](https://github.com/sadevaraj/aidevtools_prj/issues/11). It is preparation
only: issue #16's local image work does not push GHCR images, create Render
resources, enter secrets, or deploy. Do not modify or use Kanban resources.

The [issue #12 pipeline runbook](pipeline.md) covers the separately approved
CI/GHCR/opt-in development CD implementation. The
[later approval](https://github.com/sadevaraj/aidevtools_prj/issues/12#issuecomment-6428965305)
allows implementation before #13, but **CD stays disabled until deployed
verification and owner setup**. Initial manual deployment below is still needed.
No new workflow/registry/deployment success is claimed; the hosted frontend's
latest reported proxied API check was HTTP 502. Local telemetry is not Render
telemetry; Actions failure notifications are not runtime alerts or automatic fixes.

## Delivery order and local gate

1. Build and validate the frontend/backend runtime images locally with
   `sh scripts/test.sh`, the production-like Compose stack, and the browser
   journey. From the repository root, create fresh disposable local-only values
   and start the named production-image test stack:

   ```sh
   POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
   SESSION_SECRET="$(openssl rand -hex 32)" \
   docker compose -p sudoku-issue16-smoke -f compose.prod.yaml up --build --detach
   ```

   Open `http://localhost:18080`. Complete the journey documented in README:
   register/login, check three puzzles, save and resume after
   `docker restart sudoku-issue16-smoke-backend-1`, complete a board and confirm
   it is read-only, log out, and verify another disposable account sees no games.
   Sign out and clean only this isolated stack and database volume:

   ```sh
   POSTGRES_PASSWORD=cleanup SESSION_SECRET=cleanup \
   docker compose -p sudoku-issue16-smoke -f compose.prod.yaml down --volumes --remove-orphans
   ```

   The generated values are not needed for teardown; the harmless placeholders
   only satisfy Compose interpolation. Never use the smoke project name for a
   non-test stack or remove any other project/volume.
2. From a clean, reviewed commit, run `sh scripts/build-images.sh`. Use the same
   full commit SHA for both images. The optional second argument adds a paired
   extra tag; it does not replace the SHA tag. Do not publish a tag made from
   dirty or unreviewed source.
3. The owner logs in to GHCR and manually pushes both public packages. Agents do
   not push or change registry settings.
4. The owner creates one new Free Render PostgreSQL database dedicated to
   Sudoku and two image-backed Web Services. Never use a Kanban database or
   credentials. Choose an available region once and use that same region for the
   database and both services. The owner must confirm free-tier availability
   before provisioning; the free database has a 1 GB limit, expires after 30
   days, and has no managed backups. Plan an owner-operated export before expiry.
5. After the owner deploys the paired image tags, agents verify deployed behavior
   and rollback under issue #13. Issue #12's implementation may proceed earlier
   under the approval above, but automatic CD must remain off until #13 passes
   and the owner completes the pipeline setup. Do not report local results as
   Render verification.

### Deployment choice still requiring owner confirmation

Issue #11 fixes the database as Free but does not choose a compute plan for the
two Web Services. Do not assume that the web services are free or authorize a
paid plan. This also affects the proxy route: Render's
[private-network documentation](https://render.com/docs/private-network) states
that Free Web Services can send private-network requests but cannot receive
them. If the backend uses a plan that cannot receive private traffic, the
frontend proxy must use the backend's public HTTPS service URL as
`API_UPSTREAM`; the browser still talks only to the frontend origin. Use the
backend Internal URL only if the selected backend plan supports inbound private
network traffic. The owner/coordinator must confirm the web-service plans and
route before provisioning or deployment.

**Owner action:** before creating either Web Service, choose the instance plan
for each service and confirm the associated cost/availability in the Render
dashboard. If the backend is on Free, configure the frontend's `API_UPSTREAM`
with the backend's public HTTPS URL. If the owner chooses a plan that supports
receiving private-network traffic, the backend internal service URL may be used
instead. In both cases, the browser calls only the frontend service's same-origin
`/api/` proxy; do not point frontend code or browser requests directly at a
cross-origin backend.

## Owner: manually publish images

The packages are public so Render does not need registry credentials. For
manual publication, the owner uses a GitHub credential with the `write:packages`
scope:

```sh
docker login ghcr.io --username YOUR_GITHUB_USERNAME
docker push ghcr.io/sadevaraj/simple-sudoku-backend:<full-commit-sha>
docker push ghcr.io/sadevaraj/simple-sudoku-frontend:<full-commit-sha>
```

Enter the credential only at Docker's interactive password prompt. Do not put it
in command arguments, files, logs, or this repository. Confirm that both
packages are public and that the tags refer to the same reviewed commit.

## Render database

In the Render dashboard, create a new PostgreSQL database for Sudoku, using the
Free plan and the same owner-selected region as the two services. Use a distinct
Sudoku database name. Do not select, reuse, or modify any Kanban resource.
Copy the database's **Internal Database URL** from its dashboard for the backend
`DATABASE_URL` setting below. Keep that URL private and enter it only in Render's
environment-variable UI. Render supplies the credentials in that URL; do not
copy them into source, chat, issue comments, or logs.

## Render backend Web Service

Create a new Web Service from an existing public container image. Suggested
service name: `sudoku-backend-dev`.

| Setting | Value |
| --- | --- |
| Image | `ghcr.io/sadevaraj/simple-sudoku-backend:<full-commit-sha>` |
| Region | Same owner-selected region as the Sudoku database and frontend |
| Instance type | Owner/coordinator must select; not decided in issue #11 |
| Auto-deploy | Disabled for this initial manual deployment |
| Port | `10000` |
| Health check path | `/api/health` |
| `APP_ENV` | `production` |
| `DATABASE_URL` | Sudoku database's Internal Database URL |
| `SESSION_SECRET` | Owner-generated random value, at least 32 characters; enter only in Render |
| `LOGIN_RATE_LIMIT` | `5/minute` |
| `COOKIE_SECURE` | `true` |
| `PORT` | `10000` |

The container applies Alembic migrations and idempotently validates/seeds the
three puzzles before the API process starts. `/api/health` performs a database
query, so it must not report healthy if the database or initialization is
unavailable. The browser reaches the API through the frontend proxy, not this
backend service directly.

### Optional Grafana Cloud OTLP export

Issue #17 implements authenticated HTTPS OTLP export for traces, metrics, and
logs. This is optional application code, not an applied Render setting. The
owner must configure the backend Web Service only, using private Render
environment variables and credentials from the selected Grafana Cloud stack.
Never put an ingestion token or encoded credential in Git, chat, logs, or an
issue comment. The frontend needs no OTLP credential.

In Grafana Cloud, open the selected stack's OpenTelemetry/OTLP setup and copy
its OTLP gateway endpoint and generated authentication header. Use the
stack-specific endpoint from Grafana; its generic form is
`https://otlp-gateway-<region>.grafana.net/otlp`. Add these values to the
backend service's Render environment:

| Variable | Value |
| --- | --- |
| `OTEL_ENABLED` | `true` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Grafana's HTTPS OTLP base endpoint, for example `https://otlp-gateway-<region>.grafana.net/otlp` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Grafana's generated `Authorization` header in OTLP environment-variable form; for Python, encode the space after `Basic` as `%20`, e.g. `Authorization=Basic%20<base64-instance-id-and-token>` |

Use the gateway base endpoint ending in `/otlp`, not a signal path. With
`OTEL_EXPORTER_OTLP_ENDPOINT`, the application appends `/v1/traces`,
`/v1/metrics`, and `/v1/logs` once, following the OTLP/HTTP convention. If
using signal-specific `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`,
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`, or
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` instead, each value is the complete URL for
that signal and is passed as-is. Standard signal-specific header variables
override the shared `OTEL_EXPORTER_OTLP_HEADERS` value. Every signal must have
an `Authorization` header and an HTTPS URL; invalid values stop backend
startup with a sanitized configuration error. TLS certificate verification
remains enabled. Do not set these cloud variables for the local Compose
collector; leaving `OTEL_EXPORTER_OTLP_PROTOCOL` unset preserves the existing
local HTTP traces/logs and gRPC metrics setup. Unauthenticated local mode accepts
only `http://otel-collector:4318` with `otel-collector:4317` (the Compose service),
or explicit loopback hosts `127.0.0.1`, `localhost`, and `[::1]` on HTTP port
4318 and gRPC port 4317. It does not trust arbitrary private IPs or internal-looking
DNS names. Signal-specific endpoint overrides require authenticated HTTPS cloud
mode; they cannot bypass this local boundary. Unsupported destinations are
rejected before any exporter is constructed.

After the owner applies and restarts the backend service, verify from Grafana
Cloud using a disposable account/game:

1. Save progress once through the public frontend and wait for exporter
   delivery. Confirm a `sudoku-api` trace for
   `PUT /api/games/{game_id}` appears, including the `db.save_game` child span.
2. In Logs/Explore, find the metadata-only `http_request` record for the same
   trace ID and confirm the save outcome. The record must not contain a
   username, password, session/CSRF value, cookie, request body, or board.
3. In Metrics/Explore, inspect `sudoku_save_requests` or
   `sudoku_http_requests`; confirm the save outcome is present without trace IDs
   as metric labels. Follow an available metric exemplar to its trace.
4. Confirm the save completed in the application and inspect safe backend
   diagnostics if export fails. Export outages must not prevent a save.

This runbook records no real endpoint, credential, applied Render setting, or
remote Grafana result. No Grafana Cloud ingestion, dashboard, or remote
correlation has been verified by this implementation. The owner must check the
current stack's limits/retention and perform the above verification before
claiming remote telemetry evidence. Local Compose success is not a substitute.

References: [Grafana Cloud OTLP endpoint guidance](https://grafana.com/docs/grafana-cloud/send-data/otlp/send-data-otlp/),
[OpenTelemetry OTLP exporter environment variables](https://opentelemetry.io/docs/specs/otel/protocol/exporter/),
and [OpenTelemetry SDK environment variable conventions](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/).

## Render frontend Web Service

Create a second Web Service from an existing public container image. Suggested
service name: `sudoku-frontend-dev`.

| Setting | Value |
| --- | --- |
| Image | `ghcr.io/sadevaraj/simple-sudoku-frontend:<same-full-commit-sha>` |
| Region | Same owner-selected region as the Sudoku database and backend |
| Instance type | Owner/coordinator must select; not decided in issue #11 |
| Auto-deploy | Disabled for this initial manual deployment |
| Port | `10000` |
| Health check path | `/` |
| `PORT` | `10000` |
| `API_UPSTREAM` | Backend URL reachable from the frontend service: public HTTPS URL if the backend plan cannot receive private traffic; internal URL only if it can |

Nginx serves the built frontend and proxies same-origin `/api/` requests to
`API_UPSTREAM`. Even when the upstream is the backend's public URL, the browser
only contacts the frontend origin; this proxy design does not require browser
CORS or cross-site cookies. Keep CSRF cookies and request headers flowing
through the proxy. The backend sets HttpOnly, SameSite=Lax, Secure session
cookies for this HTTPS deployment; do not disable `COOKIE_SECURE`. See
[Render port binding](https://render.com/docs/web-services#port-binding) for
the `PORT` setting.

### HTTPS upstream routing and health diagnosis

Set `API_UPSTREAM` to the backend origin only, for example
`https://simple-sudoku-backend.onrender.com` for the owner's Free backend.
Do not append `/api`, a path, or a trailing slash: nginx must preserve the
browser's `/api/...` path. Local Compose continues to use
`http://backend:8000`.

The frontend uses the upstream authority (`$proxy_host`) for the HTTP `Host`
header and the upstream hostname for TLS SNI and certificate-name verification.
Both are necessary when the upstream is behind Render's shared HTTPS router.
Using the browser/frontend hostname as upstream `Host` routes to the wrong
service; omitting SNI can fail the TLS handshake with nginx returning 502.
HTTPS upstream certificates are verified against the nginx image's system CA
bundle at `/etc/ssl/certs/ca-certificates.crt`, with verification depth 3.
Do not disable verification to work around certificate failures. HTTP Compose
upstreams do not perform TLS verification. These settings follow nginx's
[proxy module directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_ssl_server_name).

This only changes upstream transport/routing identity. Browser requests remain
same-origin; cookies (including Secure/HttpOnly/SameSite attributes), CSRF
headers, Origin, and trace context pass through unchanged. Other existing
forwarded-header settings are unchanged.

The frontend `/` health check proves static serving, not API connectivity.
After an owner-operated deployment, compare these read-only probes:

```sh
curl --fail --show-error https://simple-sudoku-backend.onrender.com/api/health
curl --fail --show-error https://simple-sudoku-frontend.onrender.com/api/health
```

Both must return HTTP 200 and `{"status":"ok"}`. Direct-backend success plus
frontend 502 points to proxy connectivity/TLS/routing, not necessarily backend
or database health. A local production frontend container configured with the
public backend can verify the transport fix without deploying; that does not
establish that Render is running the fixed image or satisfy issue #13's deployed
journey/rollback checks. A new candidate still requires independent QA/review
and fresh authorization before publication/deployment.

## Deploy and roll back by tag

For the first deployment, use Render's manual image deployment action to deploy
the full SHA tag on both services. Verify the two services use the same commit
SHA before beginning browser checks. Do not enable automatic deployment as part
of this manual setup.

To roll back, use each service's manual deploy action to select the previous
verified full SHA tag from the matching GHCR package. Deploy the corresponding
frontend/backend image pair, then re-run the deployed journey checks. Before
rolling back an image, check that its code remains compatible with the database
schema; restoring an earlier image does not reverse migrations or restore data.

## Browser verification handoff

After deployment, issue #13 owns independent deployed verification. Check
registration/login, exactly three puzzles, save/resume after a backend service
restart, backend-validated completion becoming read-only, logout, and account
isolation through the frontend's public same-origin URL. Also verify that
state-changing requests without a valid CSRF token are rejected and that session
cookies have HttpOnly, SameSite, and Secure attributes. Record deployed version
and evidence in #13 without including secrets, cookies, or account credentials.
