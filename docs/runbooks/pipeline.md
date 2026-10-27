# CI, image publication, and opt-in Render development delivery

## Readiness and authority

Issue [#12](https://github.com/sadevaraj/aidevtools_prj/issues/12) implements this
pipeline under the [agent-recorded human approval](https://github.com/sadevaraj/aidevtools_prj/issues/12#issuecomment-6428965305).
That approval permits **implementation before #13**, not deployment before
verification. Earlier delivery-order notes in the architecture/manual runbook
describe the original sequence; this limited resequencing does not remove any
deployed acceptance gate.

The workflow is source configuration, not evidence that GitHub has run it.
No workflow run, deliberate remote failure gate, GHCR publication/pull/run, or
Render deployment is claimed by this implementation. Existing manually published
images do not verify the new pipeline. Issue #12 cannot close without its actual
remote evidence and independent QA/review. Issue
[#13](https://github.com/sadevaraj/aidevtools_prj/issues/13) remains pending:
the hosted frontend's latest reported proxied API check was HTTP 502. The owner
must deploy the reviewed HTTPS proxy fix and verify the full deployed journey
and rollback before enabling CD. Local telemetry is **not Render telemetry**.

## Workflow

`.github/workflows/pipeline.yml`:

1. `pull_request` and `push` to `main` run `sh scripts/test.sh` on Linux with
   Docker Compose. This includes the offline pipeline tests, real PostgreSQL
   migrations/API/security/persistence tests, frontend tests/build, and local
   HTTP/HTTPS proxy regressions. PRs do not get registry or Render credentials.
2. Only a successful test job on a `main` push in this exact repository allows
   publication. The publication job alone grants `packages: write`; defaults
   are `contents: read`. Login uses the ephemeral `GITHUB_TOKEN`, never a user
   PAT. Checkout credentials are not persisted. Actions are pinned to verified
   release commit SHAs (release names are inline comments).
3. Separate production images receive the same full `github.sha` tag and OCI
   revision/source labels. `image-pair-<SHA>` retains `image-pair.json` for 30
   days, with both tags, immutable `@sha256:…` references and pair completeness.
   The job summary repeats these references. Partial publication is recorded,
   fails the job and cannot deploy; publication is **not atomic**. Do not treat
   a lone image or an old tag as a complete candidate.
4. CD is **OFF unless both repository flags below equal the literal `true`**.
   When enabled, the development environment job consumes this run's two
   publication digests, not `latest` or a previously configured fixed SHA tag.
   It has no package-write permission. Environment secrets are only exposed to
   the deploy step, not the tests or publication job.

Main pipeline runs serialize without canceling an in-flight deployment.
GitHub concurrency can replace a pending run with a newer pending run; it is
not a durable release queue. Do not manually deploy concurrently with CD.
Timeouts are 20 minutes for tests/publication and 35 for deployment. If GitHub
cancels/kills a run or the runner is lost, final artifacts may not be uploaded:
inspect both services before retrying. Never infer failure means nothing changed.

## Owner setup — no settings changed by this implementation

First obtain independent QA/review of this diff. Only reviewed fixes may enter
`main` and deploy. The owner must use the delivery process and, where available,
main-branch rules requiring the `tests` check and reviewed changes; workflow
configuration alone does not enforce human review or protect direct main pushes.
No branch protection/environment rules are claimed configured.

Before any authorized publication, confirm both existing public GHCR packages
allow this repository's Actions `GITHUB_TOKEN` write access (package settings /
Manage Actions access) and remain public so Render can pull without credentials:

- `ghcr.io/sadevaraj/simple-sudoku-backend`
- `ghcr.io/sadevaraj/simple-sudoku-frontend`

Do not add a PAT if package permissions are wrong. Ask the owner to correct the
package/repository association. No new secret is needed for GHCR.

Create/configure GitHub environment **`sudoku-development`**, restricted to main,
only after authorized owner action. Keep the Render key in this environment,
not as a repository-wide secret. Set:

| Location | Name | Exact meaning |
| --- | --- | --- |
| Repository Actions variable | `RENDER_DEV_CD_ENABLED` | Absent or `false` initially; set `true` **last** |
| Repository Actions variable | `RENDER_DEV_VERIFIED` | Absent or `false` until #13's deployed journey/version/rollback has passed |
| Environment variable | `RENDER_DEV_VERIFICATION_URL` | Actual acceptance comment URL `https://github.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-<id>`; a URL is an owner attestation, not automatic proof of its contents |
| Environment variable | `RENDER_DEV_BACKEND_SERVICE_ID` | Exact owner-verified `srv-…` ID of the existing Sudoku development backend |
| Environment variable | `RENDER_DEV_FRONTEND_SERVICE_ID` | Different exact `srv-…` ID of the existing Sudoku development frontend |
| Environment secret | `RENDER_API_KEY` | Owner-created Render API key, least available scope for the Sudoku workspace/services |

Actual service IDs and credentials are **not available to this implementation**;
do not invent them. Copy IDs from the existing Sudoku services' dashboard URLs.
The helper cannot discover/create resources or change settings. It validates
both IDs against Render metadata **before either POST**, requiring:

| Role | Exact service name | Exact service URL | Configured image repository |
| --- | --- | --- | --- |
| Backend | `simple-sudoku-backend` | `https://simple-sudoku-backend.onrender.com` | `ghcr.io/sadevaraj/simple-sudoku-backend` |
| Frontend | `simple-sudoku-frontend` | `https://simple-sudoku-frontend.onrender.com` | `ghcr.io/sadevaraj/simple-sudoku-frontend` |

Both must be image-backed Web Services with Render auto-deploy disabled
(`autoDeploy: no`). A metadata/name/URL/image mismatch blocks deployment; request
an explicit corrected target decision rather than relaxing these checks.
Do not use Kanban/production IDs. Render API keys may have broader access than
the helper: the owner must check available key/workspace permissions and keep
the secret isolated. Code allowlisting is not a provider-side credential scope.
Retain all database/session/cookie/proxy settings in the
[manual runbook](render-development.md). This pipeline does not change them or
receive database URLs/session secrets.

## Exact-image Render mechanism

Official references checked for this implementation:

- [Trigger deploy API](https://api-docs.render.com/reference/create-deploy):
  `POST https://api.render.com/v1/services/<service-id>/deploys`, JSON
  `{"imageUrl":"ghcr.io/sadevaraj/simple-sudoku-<role>@sha256:<digest>"}`.
  The host/repository/image must match the service's configured image.
- [Retrieve deploy](https://api-docs.render.com/reference/retrieve-deploy):
  `GET /v1/services/<service-id>/deploys/<deploy-id>` returns status and
  `image.sha` (the resolved digest).
- [Retrieve service](https://api-docs.render.com/reference/retrieve-service):
  service identity, `imagePath`, auto-deploy setting and runtime/URL preflight.
- [Deploying an image](https://render.com/docs/deploying-an-image):
  image-backed services do not follow a changed registry tag automatically.

The helper uses authenticated API calls to explicitly select each immutable
image; it does not call a generic deploy hook or assume fixed SHA settings update
themselves. Per-deploy overrides do not imply that future dashboard deploys use
this pair: always inspect/select exact image references.

Order: preflight both → POST backend → poll backend live and exact digest →
direct backend `/api/health` → POST frontend → poll frontend live and exact
digest → proxied frontend `/api/health` and frontend `/` → recheck both deploys'
live status/digests. Each deployment poll is bounded to 600 seconds with 10-second
intervals; each health check to 120 seconds; requests timeout after 20 seconds.
Unknown/failed/canceled states, digest mismatches, authentication/API errors,
untraceable queued responses without a deploy ID, and timeouts fail closed.
POSTs are **never retried**: an ambiguous response might already have deployed.
HTTP redirects are refused; bearer headers never go to health endpoints.
Provider responses/error bodies and credentials are not printed.

`render-development-<SHA>` retains `deployment-result.json` for 30 days, and
the step summary records per-service IDs, deploy IDs, images, phase and sanitized
failure. `verified` means the API reported the exact live digests and the health
probes passed, **not** that every product journey was exercised. Application
health currently has no commit endpoint; version verification uses Render's
resolved digest, not a fictional version response. An authorized first API
deployment must confirm the real response schema/digest representation and the
artifact against Render; mismatches block rather than guess.

## Enabling and independently verifying

1. Keep both flags off; finish #13 and record deployed version, full user
   journey, security/ownership checks and rollback with independent evidence.
2. Obtain authorization for actual source publication/workflow execution.
   Link real PR/main successful runs and an authorized deliberate failing-test
   run proving publication is skipped. Do not weaken tests to demonstrate it.
3. Pull/run **both immutable references** in an authorized isolated environment;
   record actual digests and results. Local mocks do not satisfy remote gates.
4. Owner configures the environment, correct package access, exact IDs, key,
   branch restrictions, review process, and verification URL. Set the verified
   flag only from actual #13 evidence, then enable CD last.
5. On the first authorized main deployment, compare artifacts to both Render
   deployments and verify the browser journey. Link actual runs/deployments in
   #12/#13. If anything is missing, disable CD and report BLOCKED.

No `workflow_dispatch`, remote workflow trigger, provisioning, or deployment is
performed by the developer. Mocks make no network mutations:

```sh
python3 -m unittest discover -s backend/tests -p test_pipeline.py -v
sh scripts/test.sh
```

The first command requires local Python 3 and the existing PyYAML dependency
(provided by `uvicorn[standard]` in the backend test image); it is optional.
The root command runs these same tests in Docker, requiring no host Python.

## Failures, notifications, and operator fallback

### Diagnose a blocked service preflight

Preflight checks both services before issuing either deployment POST. A failure
identifies the role (`backend` or `frontend`), exact metadata field, whether it is
`missing` (key absent) or `invalid` (present but not accepted, including null),
and the expected safe value. For example:

```text
CD BLOCKED: backend service serviceDetails.runtime invalid; expected image.
CD BLOCKED: frontend service autoDeploy missing; expected no.
```

Only code-defined field names and safe expectations are reported. Rejected
values, raw service metadata, API response bodies, and bearer credentials must
not be printed or attached to issues. Diagnose the precise field in the error:

| Field | Diagnosis / required evidence |
| --- | --- |
| `id` | Must match the owner-configured service ID; the expected ID is intentionally not echoed. Confirm the intended Sudoku development target. |
| `type`, `name` | Must be `web_service` and the role's exact `simple-sudoku-…` name listed above. |
| `serviceDetails` | Must be an object; a missing/invalid container blocks inspection of its children. |
| `serviceDetails.url` | Must be the role's exact fixed public Sudoku URL listed above. |
| `serviceDetails.runtime` / `serviceDetails.env` | Must be `image`. The existing fallback checks `env` only when `runtime` is absent, not when it is null or invalid. The diagnostic names the selected key, or both keys if neither is present. |
| `autoDeploy` | The current preflight requires the response field to be exactly the string `no`; missing, null, or other values block. |
| `imagePath` | Must be the role's exact GHCR repository with a valid tag or lowercase SHA-256 digest; no other repository or malformed reference is accepted. |

Render's official [image deployment documentation](https://render.com/docs/deploying-an-image)
says image-backed services do not automatically redeploy when a registry tag
changes, and documents the **Manual Deploy** control. Seeing that button alone
is **not evidence** that the API returns `autoDeploy: no`. The generic SDK's
`autoDeploy` field is deprecated in favor of `autoDeployTrigger`, but that does
not establish the actual response shape for these image-backed services.
This fix neither removes the `autoDeploy` safeguard nor treats the newer field
as compatible evidence.

Do not blindly retry the job or change settings/targets to silence an error.
Keep CD disabled while the precise mismatch is unresolved. If provider schema
compatibility is suspected, request a separately authorized, sanitized
field-presence/type investigation and an explicit compatibility decision before
changing validation. Do not fetch or dump authenticated metadata as part of
ordinary troubleshooting. Missing metadata is not proof of disabled auto-deploy.
After a reviewed fix, obtain authorization before any new workflow/deploy run;
local diagnostic tests are not deployment verification.

### Notifications and fallback

Owner: in GitHub **Settings → Notifications → System → Actions**, enable
notifications for workflow failures (email/web delivery and failure-only options
are account-controlled). Verify the preferred address/channel and prove receipt
with an authorized failure run. Repository watching alone is not proof of Actions
email delivery. No email preferences or notification delivery are claimed
configured. See [GitHub notification settings](https://github.com/settings/notifications).

This is **GitHub Actions failure notification**, not log-based alerting,
Render telemetry, runtime on-call, or autonomous repair. Failures require operator
triage and fixes reviewed before deployment. No responder agent is started.

For a failed or partial deployment:

1. Owner disables `RENDER_DEV_CD_ENABLED`; inspect both Render deploy timelines
   and the artifact. A backend may be live while the frontend remains old.
   Do not blindly rerun a POST after timeout/transport failure.
2. Record the current pair and previous verified pair's immutable references
   from retained artifacts (save release evidence longer than 30 days if needed).
   Decide roll-forward or fallback; no atomicity/automatic rollback is promised.
3. Check database migration compatibility first. Image rollback cannot undo
   migrations or restore data. If incompatible, stop for a database recovery
   decision; never reset the database or use Kanban resources.
4. Using the owner's Render manual image deployment controls, explicitly select
   the previous verified backend/frontend references as a pair, verify resolved
   digests, direct/proxied health and the full journey. See the
   [manual rollback steps](render-development.md#deploy-and-roll-back-by-tag).
   If the dashboard cannot select the exact digest, use the matching retained
   SHA tag only after confirming it still resolves to that digest.
5. Record the incident/result, review the fix, and re-enable only after fresh
   verification. This pipeline does not authorize an operator action by itself.
