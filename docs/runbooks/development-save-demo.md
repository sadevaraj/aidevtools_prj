# Owner-operated development save-recovery demo (#20)

**Status: implementation only; live chain NOT RUN.** Local PostgreSQL/CLI mocks
are not Grafana, Copilot, GHCR, Render, rollback, or deployed recovery evidence.
[Latest agent-recorded human approval, 28 October 2026 00:22 +01:00](https://github.com/sadevaraj/aidevtools_prj/issues/20#issuecomment-6456057621)
records “i want grafana triggered fix” then “yes” to the MAIN-based Grafana chain:
deliberate-error commit on MAIN → approved development fault deployment → failed
Save → Grafana alert → tested Copilot fix PR MAIN → manual owner merge → normal
deployment. Earlier branch/separate-workflow and CI-only designs are superseded,
not delivered. Only local implementation/tests/docs are authorized now.
Keep #20 open until its real live acceptance evidence exists.

The [agent-recorded owner approval, 28 October 2026 ~08:49 +01:00](https://github.com/sadevaraj/aidevtools_prj/issues/20#issuecomment-6463679181)
adds one explicit **unverified-access, one-attempt** alternative below. The real
Grafana-triggered repair must be the first model attempt: no provider smoke,
eligibility probe, retry, or recursive model loop. Candidate and mandatory
independent QA/Reviewer sessions constitute that one repair attempt. The owner
accepts unknown access/failure and rollback within **15 minutes from fault
deployment**. Deterministic local tests remain required. This local patch does
not authorize live execution, paid enablement, account changes, or auto-merge.

## 1. Stop prerequisites — do not substitute flags for proof

The owner must explicitly approve a short development-only window, its stop
time, affected disposable test account, and the healthy rollback pair. Before
that window, record in #13/#20:

- Independent #12/#13 delivery and deployed verification evidence: exact
  healthy frontend/backend digests, login, owner-only save/reopen, restart
  persistence, immutable clues, backend completion checks and completed-game
  immutability. Rehearse rollback and verify those same healthy digests.
  The user's reported corrective deploy/login/save is attributed evidence,
  **not** independent completion of #13. Main is currently unprotected:
  manual merge is procedural, not a technical branch-protection claim.
- Exact Sudoku development service IDs, image-backed runtime, fixed public
  frontend/backend origins, database/migration compatibility, and a tested
  owner-operated rollback. Never use Kanban/production. Image rollback does
  not undo migrations; 0002/0003 remain intact and 0004 adapts the authorization
  branch constraint/replay index only. Historical approvals are not converted
  into MAIN approvals. Do not
  downgrade schema or delete/reset player data as a demo repair.
- Either actual repository/Actions Copilot CLI entitlement, usable Free quota for
  coordinator/DEV and two independent review sessions, no paid overage, and
  explicit approval to send this public repository's source to Copilot.
  **Or**, only in the existing durable development-control-required repair
  path, explicit owner `REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED=true`
  accepts unknown entitlement/quota for the single attempt above. Leave
  `REPAIR_FREE_ENTITLEMENT_CONFIRMED` / `REPAIR_QUOTA_CONFIRMED` unset/false
  unless actually verified; never fabricate confirmations. Mandatory
  `REPAIR_NO_OVERAGE_CONFIRMED=true` requires the owner's no-paid/no-overage
  authorization and provider-side controls; privacy and enablement gates remain.
  These flags do **not** enforce provider billing, guarantee free execution, or
  prove dollar safety. Do not enable paid usage. If no-paid controls cannot be
  established, **STOP** even on the unverified-access path.
  Otherwise unknown access means **STOP**. `true` variables are owner attestations, not probes;
  token presence is not proof of permissions. The undocumented
  `chat199/200 premium0` endpoint does not establish Actions CLI entitlement.
  The workflow does not discover quotas, purchase capacity, or enable billing.
- Privately supplied, least-privilege credentials with independently verified
  permissions. The reportedly misplaced token in a repository **variable** is
  NOT a valid secret. The owner must rotate it, remove that variable and
  recreate the proper `ALERT_REPAIR_PR_TOKEN` secret privately, then verify its
  permissions. Do not inspect/print/copy the old value or create credentials in an
  agent session, paste values into chat/issues, or print environment dumps.
- Real telemetry reaches Grafana Cloud; the approved save-5xx firing rule and
  authenticated webhook contact point match the existing alert configuration.
  Expected 4xx, query errors, and no-data are not qualifying incidents.
  The backend receiver cannot accept an alert while the backend is down.
- DEV -> independent Prj_QA -> Prj_Reviewer reports cover the same implementation
  revision/diff, including product/guard comparison and approval evidence.
  Local role evidence does not establish the future runtime agent gates.

If any other prerequisite is unavailable, keep all flags off and record BLOCKED.
Only the exact approved access-risk exception supersedes unknown-access-means-stop;
unknown defects and other unknown prerequisites still stop. No extra provider
smoke/eligibility request is permitted.

## 2. Owner configuration (future authorized operations only)

These are instructions, **not commands executed by this DEV task**.
Use private provider settings/secret inputs. Existing configuration is documented
in [the pipeline runbook](pipeline.md) and
[Render runbook](render-development.md). Preserve cookie, DB and proxy settings.

| Location | Required configuration |
|---|---|
| Development backend | `APP_ENV=development`, `COOKIE_SECURE=true`, migrations through 0004, `ALERT_REPAIR_ENABLED=true`, `DEMO_CONTROL_ENABLED=true`; private `ALERT_RECEIVER_TOKEN`, restricted Actions-dispatch `ALERT_DISPATCH_TOKEN`, distinct `DEMO_CONTROL_TOKEN` |
| Repository variables | `ALERT_REPAIR_AUTH_URL=https://simple-sudoku-backend.onrender.com/api/alerts/repair/claim`; `ALERT_REPAIR_ENABLED=true`, `DEMO_CONTROL_ENABLED=true` |
| Mandatory repair variables | `REPAIR_COPILOT_OWNER_ENABLED`, `REPAIR_NO_OVERAGE_CONFIRMED`, `REPAIR_PROVIDER_TRANSMISSION_APPROVED` set to `true` only with owner authorization/control/evidence; flags do not enforce billing |
| Access policy alternatives | Verified: `REPAIR_FREE_ENTITLEMENT_CONFIRMED=true` and `REPAIR_QUOTA_CONFIRMED=true` with real evidence. Approved unverified path only: `REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED=true`, without asserting unknown confirmations; requires `DEMO_CONTROL_REQUIRED=true` (fixed pipeline), `DEMO_CONTROL_ENABLED=true`, repair mode and all existing durable checks |
| Repository secret | Owner-managed `ALERT_REPAIR_PR_TOKEN` with verified repository contents/PR permissions; not a CLI credential |
| Existing `sudoku-development` environment | Owner-reviewed MAIN dispatch access; private `DEMO_CONTROL_TOKEN` matching the backend and `RENDER_API_KEY`; verify actual access restrictions rather than assuming the name enforces review. No new demo environment |
| Demo variables | `DEMO_FAULT_ENABLED`, `DEMO_FAULT_DEPLOY_APPROVED`, `DEMO_ROLLBACK_PAIR_VERIFIED`, `DEMO_WINDOW_CONFIRMED`, `DEMO_IMAGE_PROVENANCE_VERIFIED`, `DEMO_TARGETS_CONFIRMED` all `true`; verified #13 comment `DEMO_ROLLBACK_EVIDENCE_URL`; paired `DEMO_ROLLBACK_BACKEND_DIGEST` / `DEMO_ROLLBACK_FRONTEND_DIGEST`; explicit UTC `DEMO_EXPIRES_AT` no more than one hour ahead |
| Delivery configuration | Exact `RENDER_DEV_BACKEND_SERVICE_ID`, `RENDER_DEV_FRONTEND_SERVICE_ID`, `RENDER_DEV_VERIFICATION_URL` equal to the rollback evidence URL; private environment-scoped Render key as in the pipeline runbook |
| Trusted tooling variable | `DEMO_TRUSTED_REVISION=T`, the full reviewed healthy MAIN SHA including this single pipeline, scripts, pinned regression and migrations |

Names in this table do not establish that secrets, permissions, environment
protection or entitlement are configured. The fault workflow uses the normal
job token only for image publication. Candidate and review containers forward
only the short-lived read/Copilot token, not OIDC/DB/deploy/PR credentials.
The pinned runtime needs registry/npm installation access and Copilot provider
network access during the **future approved run**; none is exercised locally.
Unknown CLI/Actions support or an unsupported flag fails closed, not into a
fallback provider, billing plan, broader tool allowlist, or bypass.

## 3. Create and validate T/F (owner only, after separate publication authority)

First pass DEV → independent QA → Reviewer and merge the reviewed **healthy**
implementation to MAIN through the usual process. This task does not
commit/push/merge it. Deploy and verify that healthy T pair and rollback under
#12/#13; set the immutable `DEMO_TRUSTED_REVISION` owner variable to T. Baseline
`692bb618c1325a4edf97b4e66ab23cefb6916583` is the old healthy T, not the
future T for this changed policy. Changing trusted scripts/workflow/tests requires
a **NEW reviewed healthy T**, then a **NEW exact one-line child F**. Recompute
the trusted pin, expected repaired tree, immutable image pair and server
authorization. Never patch old faulty `4b84702479fcf31f2277732397ee48069c8dddfb`
in place or reuse its old T pin to authorize changed tooling. No such commit,
push, fault recreation or live configuration is performed by this local task.

The old published healthy recovery pair for `692bb6…` is retained:
backend `sha256:b0ece8540edd1a752f47429bdef4b26db189e4193b8d502776b4a097dc275553`,
frontend `sha256:b85005dba53d68733ec44698715d63e9ff59fc5267022f596bbb7ad249e54731`.
[Owner-reported deployment/save evidence](https://github.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-6463370504)
is not independent rollback verification. That recovery pair can remain only
if schema/control compatible; image rollback is never a database downgrade.

Only in a separately authorized owner window and clean owner checkout, create
one deliberate fault commit F directly on MAIN after T. Change **only**
`game.board = _validated_board(body.board, puzzle.clues)` to
`game.board = _validated_board(body.borad, puzzle.clues)` inside save_game,
retaining indentation. Do not modify tests, workflows, instructions or other
files. Inspect the exact diff, record T/F and window in #20, then the owner
alone may publish F to MAIN. This is intentionally broken development source,
not an agent action authorized by this local task.

Normal F push CI **must fail** the ordinary save tests and publish/deploy
nothing. Do not mark the failures expected or use continue-on-error.
Do not advance MAIN during the demo. Failed CI does NOT trigger repair.

After confirming the exact known fault and gates, only repository owner
`sadevaraj` can dispatch fault mode (not a collaborator or a rerun). The owner dispatches
the existing pipeline at MAIN F (future operations, NOT run here):

```sh
gh workflow run pipeline.yml --ref main -f mode=fault
gh run list --workflow pipeline.yml --limit 5
```

There are no arbitrary T/F/ref/command inputs. T is the owner-pinned full SHA;
F is the dispatch's immutable MAIN SHA. Before executing the trusted helper,
the workflow checks T's SHA syntax. T's helper then requires its own HEAD=T,
current remote MAIN=F, workflow SHA=F and fixed repository/event/workflow ref.
Only the exact one-commit T..F typo is permitted, so workflow, scripts and tests
at F are identical to T. MAIN movement or any other fault stops.

The fault mode runs the **full ordinary suite on healthy T**, copies only F's
authorized save source into T's disposable harness, and proves authenticated
HTTP 500, unchanged board and repaired persistence on tmpfs PostgreSQL. That
special fixture does **not** make F's ordinary CI green or create a general
failed-test bypass.

Unprivileged jobs build both F images into same-run/attempt archives. A fresh T
publisher rechecks branch/delta/window and image source/revision labels, then
pushes only those archives and records immutable digests. A trusted owner
environment step arms the healthy server with the exact T/F, repaired tree,
fixed targets, fault/rollback pair, evidence URL and expiry **before deployment**.
Fault dispatch reruns (attempt >1) are rejected. Arming an already-active demo
or any previously authorized MAIN F returns conflict, even after expiry/revoke.
Deployment preflight refuses a
current healthy pair different from the verified rollback digests, wrong
service identity, missing health, expired window, or incomplete image pair.
Partial/ambiguous publication or deploy must be treated as STOP, not retried.

Record the workflow URL and both immutable fault references from the publish
step outputs/log (no credentials). Preserve healthy rollback references
separately. There is no automatic production action or database rewrite.

## 4. Real alert, trusted repair, manual merge, exact recovery

1. Owner authenticates using the approved disposable account and performs a
   valid manual save. Record its actual 500 and lack of false success, unchanged
   persisted progress on reopen, metric/trace/log IDs, firing alert and delivery
   evidence. Do not export cookies, passwords, bearer headers or board data
   into public evidence. Business-user accounts are not demonstration fixtures.
2. Grafana sends only to the fixed authenticated receiver. The server associates
   the incident with its armed T/F record. It dispatches only `pipeline.yml` on
   MAIN with `mode=repair`, opaque incident ID and server expiry, never a
   payload-selected ref or failed-CI substitute.
   The alert TTL is at most 30 minutes and never exceeds the owner's window.
3. Authorization uses the same pinned T tooling/current F workflow checks as
   fault mode; server-issued T/F must equal that pair. The server verifies
   signed OIDC for `pipeline.yml@refs/heads/main`, workflow SHA=F and one
   run/attempt claim. Candidate Copilot
   operates on F in a resource-limited container using read-only T instructions.
   Only the exact typo correction is accepted. The staged repaired tree must
   equal T; T's full harness runs and records the F/patch/tree/run/attempt
   receipt, including `unverified_access_one_attempt_approved` when the owner
   accepts unknown access (not an entitlement/quota or billing claim).
   Two distinct read-only QA and Reviewer CLI sessions must return
   current-candidate PASS with no findings. Stale/failed/missing evidence,
   moved refs, replay/reruns, unsupported patches and expired/revoked claims
   block publication. Do not rerun an already-consumed attempt to bypass it.
4. The credentialed publisher executes only T tools, rechecks server
   authorization and the live MAIN tip, and opens a temporary repair branch/PR
   with base MAIN at F. Publisher never executes candidate code; no permanent
   demo branch/environment exists. No agent auto-merges. Inspect the PR's one-line
   diff, normal PR CI, runtime receipt, QA/Reviewer evidence and current base.
   Branch movement at any point means STOP; there is no remote branch lock.
5. Before merging confirm the repaired PR tree equals T, all runtime evidence
   is current, the owner window remains unexpired and MAIN still equals F.
   Enable ordinary `RENDER_DEV_VERIFIED`/`RENDER_DEV_CD_ENABLED` only using real
   #13 evidence and the approved window. Enablement is owner authority, not
   supplied by Grafana or an agent.
6. Owner manually merges the reviewed PR using **Create a merge commit**,
   never squash/rebase/fast-forward, directly onto unchanged F. For a reviewed
   PR number `N`, the owner command is `gh pr merge N --merge` (no `--auto`).
   The two-parent merge's first parent must be F and its tree and repair-parent
   tree must equal T. Any extra commit/path, stale F/T, or expired window blocks
   the owner's acceptance. Ordinary main delivery uses no special repaired-tree
   bypass: the ordinary full suite runs first, then gated paired publication,
   then exact-digest development deployment. Record merge SHA, successful run,
   pair artifact, both actual Render deploy IDs/resolved digests and health.
7. Verify actual authenticated save, logout/login/reopen, refresh and backend
   restart persistence on the **repaired deployed pair**, owner-only access,
   unchanged clues and completed-game protections. Record alert recovery after
   the five-minute observation window and correlated telemetry; health alone
   is insufficient. Report quota use and any partial result honestly.

No local mock, hard-coded success report, receipt field, health response or
owner boolean substitutes for this live evidence.

## 5. Stop, revoke and owner rollback

Stop for access uncertainty unless covered by the exact approved one-attempt
exception above; privacy/no-paid-control uncertainty always stops. Stop for wrong targets, changed refs,
missing credentials/permissions/evidence, expired window, tests/reviews failure,
unknown fault, provider access/quota failure, timeout or ambiguous provider response.
The owner window is 15 minutes from fault deployment, not 15 minutes from the
first model response. On failure/timeout restore compatible healthy images;
do not retry the model attempt or run a smoke first. Clear
`REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED` along with repair enablement.
Never start a recursive repair, widen scope, enable billing, retry deployment POSTs, or merge without
the owner's decision.

Immediately cancel the affected Actions runs in the UI or
`gh run cancel RUN_ID`; disable `DEMO_FAULT_ENABLED`,
`DEMO_FAULT_DEPLOY_APPROVED`, both ordinary CD flags
and repair enablement. Revoke the durable authorization while the owner control
route is still enabled. With the existing secret present only in private
process environment, the owner can use:

```sh
curl --fail --silent --show-error --request POST \
  --header "Authorization: Bearer $DEMO_CONTROL_TOKEN" \
  https://simple-sudoku-backend.onrender.com/api/alerts/demo/revoke
```

Do not use verbose curl, shell tracing or shared shell-history capture. Revoking
requires the distinct owner bearer (not a cookie), affects armed/claimed
authorizations and rejects later verification even for a previously accepted
run. Revocation does not kill a running job; cancellation plus disabled owner
delivery gates is also required. Then disable backend `ALERT_REPAIR_ENABLED`
and `DEMO_CONTROL_ENABLED` using private owner settings. Do not erase outbox
rows as a substitute for revocation.

Owner restores **both** previously verified healthy immutable references using
Render's manual exact-image procedure in
[the deployment runbook](render-development.md), never a mutable tag or generic
deploy hook. Select backend and frontend explicitly; inspect each resolved
digest and wait for live/health. Partial rollout is non-atomic: stop and inspect
both actual deployments before any further action. Recheck authenticated
save/reopen/persistence and alert recovery after rollback, and post actual
evidence. Do not downgrade/delete the database to roll back images.

After recovery, leave demo/repair/CD flags off, record what actually ran and
what did not, and retain incident/run/attempt, T/F/merge, immutable pair,
receipt, independent reports and owner decision links. A new demo requires a
new explicitly approved window and authorization; do not extend/reuse a
consumed claim. Closing #20 remains the coordinator's decision after its
independent QA/review and live criteria, never the DEV worker's.
