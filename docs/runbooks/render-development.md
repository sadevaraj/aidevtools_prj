# Manual Render development deployment

This runbook records the owner-operated sequence from issue
[#11](https://github.com/sadevaraj/aidevtools_prj/issues/11). It is preparation
only: issue #16's local image work does not push GHCR images, create Render
resources, enter secrets, or deploy. Do not modify or use Kanban resources.

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
   and rollback under issue #13. CI-gated image publication is deferred to issue
   #12. Do not report local results as Render verification.

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
