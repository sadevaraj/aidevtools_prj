# Owner-operated development save-recovery demo (#20)

**Status: implementation only; live chain NOT RUN.** Local PostgreSQL/CLI mocks
are not Grafana, Copilot, GHCR, Render, rollback, or deployed recovery evidence.
[Exact agent-recorded human approval](https://github.com/sadevaraj/aidevtools_prj/issues/20#issuecomment-6454530534)
permits this bounded future exception, not execution during implementation.
Keep #20 open until its real live acceptance evidence exists.

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
  not undo migrations; migration 0003 adds control tables/columns only. Do not
  downgrade schema or delete/reset player data as a demo repair.
- Actual repository/Actions Copilot CLI entitlement, usable Free quota for
  coordinator/DEV and two independent review sessions, no paid overage, and
  explicit approval to send this public repository's source to Copilot.
  Unknown means **STOP**. `true` variables are owner attestations, not probes;
  token presence is not proof of permissions. The undocumented
  `chat199/200 premium0` endpoint does not establish Actions CLI entitlement.
  The workflow does not discover quotas, purchase capacity, or enable billing.
- Privately supplied, least-privilege credentials with independently verified
  permissions. `ALERT_REPAIR_PR_TOKEN` is reported missing and
  `ALERT_REPAIR_ENABLED` absent at handoff. Do not create credentials in an
  agent session, paste values into chat/issues, or print environment dumps.
- Real telemetry reaches Grafana Cloud; the approved save-5xx firing rule and
  authenticated webhook contact point match the existing alert configuration.
  Expected 4xx, query errors, and no-data are not qualifying incidents.
  The backend receiver cannot accept an alert while the backend is down.
- DEV -> independent Prj_QA -> Prj_Reviewer reports cover the same implementation
  revision/diff, including product/guard comparison and approval evidence.
  Local role evidence does not establish the future runtime agent gates.

If any prerequisite is unavailable, keep all flags off and record BLOCKED. No
live fault or paid/possibly-paid eligibility request is a valid experiment.

## 2. Owner configuration (future authorized operations only)

These are instructions, **not commands executed by this DEV task**.
Use private provider settings/secret inputs. Existing configuration is documented
in [the pipeline runbook](pipeline.md) and
[Render runbook](render-development.md). Preserve cookie, DB and proxy settings.

| Location | Required configuration |
|---|---|
| Development backend | `APP_ENV=development`, `COOKIE_SECURE=true`, migration 0003, `ALERT_REPAIR_ENABLED=true`, `DEMO_CONTROL_ENABLED=true`; private `ALERT_RECEIVER_TOKEN`, restricted Actions-dispatch `ALERT_DISPATCH_TOKEN`, distinct `DEMO_CONTROL_TOKEN` |
| Repository variables | `ALERT_REPAIR_AUTH_URL=https://simple-sudoku-backend.onrender.com/api/alerts/repair/claim`; `ALERT_REPAIR_ENABLED=true`, `DEMO_CONTROL_ENABLED=true` |
| Repair prerequisite variables | `REPAIR_COPILOT_OWNER_ENABLED`, `REPAIR_FREE_ENTITLEMENT_CONFIRMED`, `REPAIR_QUOTA_CONFIRMED`, `REPAIR_NO_OVERAGE_CONFIRMED`, `REPAIR_PROVIDER_TRANSMISSION_APPROVED` set to `true` **only after real evidence** |
| Repository secret | Owner-managed `ALERT_REPAIR_PR_TOKEN` with verified repository contents/PR permissions; not a CLI credential |
| `sudoku-development-demo` environment | Owner-reviewed dispatch access; private `DEMO_CONTROL_TOKEN` matching the backend and `RENDER_API_KEY`; verify the environment actually exists/restricts access rather than assuming its name enforces review |
| Demo variables | `DEMO_FAULT_ENABLED`, `DEMO_FAULT_DEPLOY_APPROVED`, `DEMO_ROLLBACK_PAIR_VERIFIED`, `DEMO_WINDOW_CONFIRMED`, `DEMO_IMAGE_PROVENANCE_VERIFIED`, `DEMO_TARGETS_CONFIRMED` all `true`; verified #13 comment `DEMO_ROLLBACK_EVIDENCE_URL`; paired `DEMO_ROLLBACK_BACKEND_DIGEST` / `DEMO_ROLLBACK_FRONTEND_DIGEST`; explicit UTC `DEMO_EXPIRES_AT` no more than one hour ahead |
| Delivery configuration | Exact `RENDER_DEV_BACKEND_SERVICE_ID`, `RENDER_DEV_FRONTEND_SERVICE_ID`, `RENDER_DEV_VERIFICATION_URL` equal to the rollback evidence URL; private environment-scoped Render key as in the pipeline runbook |

Names in this table do not establish that secrets, permissions, environment
protection or entitlement are configured. The fault workflow uses the normal
job token only for image publication. Candidate and review containers forward
only the short-lived read/Copilot token, not OIDC/DB/deploy/PR credentials.
The pinned runtime needs registry/npm installation access and Copilot provider
network access during the **future approved run**; none is exercised locally.
Unknown CLI/Actions support or an unsupported flag fails closed, not into a
fallback provider, billing plan, broader tool allowlist, or bypass.

## 3. Create and validate T/F (owner only, after separate publication authority)

First merge the reviewed **healthy** implementation into main through the usual
delivery process. This DEV task does not commit/push it. Set `T` to the full
healthy main SHA including these controls, and retain its paired rollback
digests. The baseline `52db42e...` alone does not include them.

From a clean owner checkout, with no unrelated edits:

```sh
git fetch origin main
git switch --create demo/save-recovery origin/main
T="$(git rev-parse HEAD)"
```

In `backend/app/main.py` change **only** the save handler's
`game.board = _validated_board(body.board, puzzle.clues)` to
`game.board = _validated_board(body.borad, puzzle.clues)`, retaining indentation.
Do not alter any tests, workflows, instructions, dependencies or other paths.
Then the owner may run:

```sh
git diff --check
git diff -- backend/app/main.py
git add -- backend/app/main.py
git commit -m "Controlled development save-recovery fault"
F="$(git rev-parse HEAD)"
git push origin HEAD:refs/heads/demo/save-recovery
```

Record T/F and owner window in #20. Main must remain at healthy T. Ordinary
demo-branch CI **must fail** its normal save regressions on F and publish
nothing. Do not remove failures, mark them expected, or set continue-on-error.
Do not advance this branch while the demo runs.

Using T's trusted script locally, with the owner attestations above supplied
privately as environment variables (not credential values in command history):

```sh
git fetch origin main demo/save-recovery
git show "$T:scripts/demo_control.py"
```

The exact-delta/ancestry gate runs again in the fixed trusted workflow:

```sh
gh workflow run development-save-demo.yml --ref main \
  -f trusted_revision="$T" -f fault_revision="$F"
gh run list --workflow development-save-demo.yml --limit 5
```

Dispatch requires main to still equal T. No generic ref/URL/command input is
accepted. The workflow runs the **full ordinary suite on healthy T**, copies
only the authorized F save source into T's disposable test harness, and proves
authenticated HTTP 500, unchanged persisted board, and repaired save/reopen
persistence against tmpfs PostgreSQL. That special fixture passing does **not**
make ordinary CI on F green.

Unprivileged jobs build both F images into same-run/attempt archives. A fresh T
publisher rechecks branch/delta/window and image source/revision labels, then
pushes only those archives and records immutable digests. A trusted owner
environment step arms the healthy server with the exact T/F, repaired tree,
fixed targets, fault/rollback pair, evidence URL and expiry **before deployment**.
Arming an already-active demo returns conflict. Deployment preflight refuses a
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
   the incident with its armed T/F record. It dispatches `repair.yml` on main
   with opaque incident ID and server expiry, never a payload-selected ref.
   The alert TTL is at most 30 minutes and never exceeds the owner's window.
3. Authorization consumes a signed OIDC run/attempt claim. Candidate Copilot
   operates on F in a resource-limited container using read-only T instructions.
   Only the exact typo correction is accepted. The staged repaired tree must
   equal T; T's full harness runs and records the F/patch/tree/run/attempt
   receipt. Two distinct read-only QA and Reviewer CLI sessions must return
   current-candidate PASS with no findings. Stale/failed/missing evidence,
   moved refs, replay/reruns, unsupported patches and expired/revoked claims
   block publication. Do not rerun an already-consumed attempt to bypass it.
4. The credentialed publisher executes only T tools, rechecks server
   authorization and the live demo tip, and opens a PR with base
   `demo/save-recovery` at F. No agent auto-merges. Inspect the PR's one-line
   diff, normal PR CI, runtime receipt, QA/Reviewer evidence and current base.
   Branch movement at any point means STOP; there is no remote branch lock.
5. Before merging, set owner variables `DEMO_RECOVERY_ENABLED=true`,
   `DEMO_TRUSTED_REVISION=T`, `DEMO_FAULT_REVISION=F`,
   `DEMO_EXPECTED_REPAIRED_TREE` to T's tree
   (`git rev-parse "$T^{tree}"`), and the still-unexpired `DEMO_EXPIRES_AT`.
   Enable ordinary `RENDER_DEV_VERIFIED`/`RENDER_DEV_CD_ENABLED` only using real
   #13 evidence and the approved window. Enablement is owner authority, not
   supplied by Grafana or an agent.
6. Owner manually merges the reviewed PR using **Create a merge commit**,
   never squash/rebase/fast-forward, directly onto unchanged F. For a reviewed
   PR number `N`, the owner command is `gh pr merge N --merge` (no `--auto`).
   The two-parent merge's first parent must be F and its tree and repair-parent
   tree must equal T. Any extra commit/path, stale F/T, or expired window blocks
   delivery. The ordinary full suite runs first, then gated paired publication,
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

Stop for quota/entitlement/privacy uncertainty, wrong targets, changed refs,
missing credentials/permissions/evidence, expired window, tests/reviews failure,
unknown fault, timeout or ambiguous provider response. Never start a recursive
repair, widen scope, enable billing, retry deployment POSTs, or merge without
the owner's decision.

Immediately cancel the affected Actions runs in the UI or
`gh run cancel RUN_ID`; disable `DEMO_FAULT_ENABLED`,
`DEMO_FAULT_DEPLOY_APPROVED`, `DEMO_RECOVERY_ENABLED`, both ordinary CD flags
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
