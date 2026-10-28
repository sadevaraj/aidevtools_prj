# Bounded development save recovery (#20 replacement)

The filename is retained for existing links, not as a fault deployment pipeline.
The [approved replacement specification](../specs/issue-20-replacement.md)
records the user's **2026-10-28T09:39:20Z “approved do it”** and exact scope.
Earlier fault-mode, demo-control, revision-pair and manual-only merge procedures
are superseded. Do not follow old commands from earlier revisions.

## Current cleanup: healthy restoration first

The developer restores healthy saving locally as maintenance, removes obsolete
operational plumbing and runs offline tests. No provider, workflow trigger,
fault deployment or live action is allowed. Only after independent QA and
Reviewer PASS on the current diff may the coordinator commit/push/deploy the
healthy simplified version to existing Render development services.

Use the ordinary [pipeline](pipeline.md) and
[Render runbook](render-development.md). Preserve PostgreSQL, migrations,
account/game data, image compatibility, Secure cookies over HTTPS and the
same-origin proxy. Do not downgrade a database to restore images.

## Future enablement prerequisites (not applied by this task)

- Independently verify the healthy development image pair, login, exact manual
  save/reopen and backend-restart persistence; retain compatible healthy digests.
  #12/#13 and remote evidence remain outstanding.
- Backend `APP_ENV=development`, `COOKIE_SECURE=true` for Render HTTPS.
  The existing master kill switch is `ALERT_REPAIR_ENABLED` (default false) on
  backend and workflow. Receiver/dispatch credentials stay private in their
  existing settings. No additional demo runtime variables are needed.
- `ALERT_REPAIR_AUTH_URL` must equal the fixed HTTPS backend
  `/api/alerts/repair/claim` URL accepted by the runner. Signed GitHub OIDC must
  identify this repository, main ref and pipeline workflow. No shared claim
  password or live database credential is sent to Actions.
- Keep existing Copilot owner consent, no-overage and provider-transmission
  attestations. Verified Free entitlement/quota may be used, or explicit
  `REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED=true` accepts unknown access for
  this one attempt without falsifying verification. Entitlement remains unknown
  here. Flags are **not provider billing enforcement**: unresolved no-paid
  controls block execution. Do not enable billing, overage or a paid plan.
- Privately correct/rotate any reportedly misplaced token variable and provide
  `ALERT_REPAIR_PR_TOKEN` as a least-privilege secret. This task does not inspect,
  copy, rotate or reconfigure credentials.
- Configure the **existing actual SAVE-ERROR LOG Grafana alert** with the
  authenticated webhook. See [alert contract](../../observability/grafana-cloud-alert/README.md).
  Preserve its real UID when updating/importing; do not create a duplicate rule.
  Payload labels must include `operation=save_game`, `service=sudoku-api`,
  `severity=warning`; `values.A` must be positive and finite. The receiver
  accepts only one firing alert and discards all raw payload fields after
  deriving the hashed fingerprint.
- Verify technical auto-merge permissions/settings and branch protection through
  authorized operator evidence, **without changing repository settings**.
  Unavailable settings/permissions are a blocker, not permission to bypass.

## Genuine alert → one repair attempt

1. Grafana's save-server-error log alert posts the authenticated HTTPS webhook.
   The receiver persists a sanitized incident before ACK, deduplicates for
   30 minutes and uses the existing bounded outbox retry/lease policy.
2. The outbox dispatches only `mode=repair` to the existing pipeline on main,
   with an opaque incident and server expiry. A signed OIDC claim consumes one
   run/attempt. Fabricated, expired and rerun incidents fail closed.
3. One Copilot candidate invocation runs in a resource-limited, non-root,
   read-only-root container. Only the read/Copilot token is forwarded; no host
   home/socket, live DB, Render, OIDC or PR writer credential is mounted.
   Instructions are read-only. Source and opaque incident are the context;
   never transmit raw logs, boards, identities, request bodies or credentials.
4. Strict patch validation permits only the known save-handler typo correction.
   It does not generate that correction. Empty or unsupported source fails.
   The unchanged pinned regression proves authenticated 500/rollback then exact
   successful save and reopen against disposable PostgreSQL.
5. A separate job executes `sh scripts/test.sh` on the exact candidate, then
   invokes distinct read-only QA and Reviewer Copilot sessions. Their PASS
   reports bind the source revision, patch hash and executed full-test receipt.
   Candidate plus these review sessions comprise one attempt, not retries.
6. Only the isolated publisher receives the PR token. It checks the current
   claim/evidence, exact tested tree and unchanged remote main, publishes a
   temporary repair PR branch without executing candidate code, waits for the
   ordinary successful PR test check and checks the exact head/base. It then
   requests `gh pr merge --auto --merge --match-head-commit …`, never `--admin`,
   force or protection bypass. If GitHub rejects it, stop and report the blocker.
7. Merge triggers the ordinary main tests → publish → existing opt-in Render
   deployment. No alternate deploy or rollback automation exists.

## Fifteen-minute fail-stop and restoration

There is **no authorization for a fault deployment now**. A later exact
`body.board` → `body.borad` fault may only be in the save handler and in a
separately confirmed, manually built development image outside normal test-gated
CI. Do not reintroduce a permanent failed-test deployment exception.

Before that separate exercise, the operator must start a **15-minute timer at
fault deployment**, remain available with compatible verified healthy image
digests and reserve time to restore and verify both services. The timer includes
Grafana evaluation, dispatch/queue/build/tests/reviews/checks/merge/deployment.
The backend additionally issues a maximum 15-minute claim deadline, shared by
runtime subprocesses and checked before merge; this later internal deadline
does **not** extend the operator's earlier deadline.

Any unsupported fault, denied access, billing uncertainty, failed test/review,
publication error, missing auto-merge permission, stalled check/deploy or timeout:
**STOP**. Disable `ALERT_REPAIR_ENABLED`, cancel remaining work, restore the
verified healthy pair via the existing Render procedure, and verify health plus
authenticated exact save/reopen before the timer expires. Cancel any pending
auto-merge request/PR so it cannot merge after restoration. Never retry a model
call or use another workflow attempt. Do not alter migrations or player data.
This is operator restoration, not claimed automatic rollback or a tested SLA.

An image-only typo while source main is healthy yields no honest fix PR. Resolve
that future source/image provenance conflict with the owner before the separate
exercise; do not fabricate an AI correction or silently weaken healthy CI.

## Evidence and current limitations

Local tests use disposable fixtures/mocks only. Remote alert routing/delivery,
Copilot access/no-paid controls, repository auto-merge availability, PR checks,
publication, Render deployment/restoration and elapsed recovery are NOT VERIFIED
by this cleanup. Record real links and exact image/check/commit identities later.
Do not close #20 based on local tests. The attributed approval/start report was
initially UNPOSTED; a later DEV comment is evidence only if its returned URL is
actually confirmed. No new issue or remote configuration change is needed here.

## Run record: 2026-10-28

Factual record of the first live exercise. Evidence:
[issue #20 comment](https://github.com/sadevaraj/aidevtools_prj/issues/20#issuecomment-6471484822).
See the [flow overview](../architecture.md#how-the-flow-works-overview).

- **Fault.** Commit `83b6a67` on main introduced `body.borad`. Normal CI run
  `40690929491` failed tests and skipped publish/deploy. The fault backend image
  was built manually outside CI,
  `ghcr.io/sadevaraj/simple-sudoku-backend@sha256:c7481028ecc9acabe0f21e1e310fbbe74283a4c2f3f3ac868c8b559c372f9180`,
  and deployed by the owner on Render.
- **Alert delivery.** The first Grafana delivery got 422 because rule labels
  `operation`/`service`/`severity` were missing; they were added. Because each
  alert identity is single-use (30-minute deduplication), retriggers needed a
  changed `attempt` label on the rule.
- **Repair run `40695042152`: blocked.** The CLI `--version` output prints an
  extra update-hint line; fixed by human maintenance commit `5f8d461`.
- **Repair run `40696710810`: blocked.** The CLI native addon could not load
  from the `noexec` `/tmp` tmpfs; fixed by human maintenance commit `4836478`
  (tmpfs `exec`, keeping read-only root, `nosuid`, `nodev`).
- **Repair run `40697952537`.** `authorization`, `candidate` and `verify`
  succeeded; branch `repair/alert-54d28cd5442c` was pushed with the one-line
  fix. `gh pr create` failed (error text not captured; suspected missing
  Pull requests write permission on `ALERT_REPAIR_PR_TOKEN`, unverified).
- **Merge and deploy.** The owner opened PR #22 manually from the agent branch;
  PR CI `40701750404` passed; the owner merged it as merge commit `12e1857`.
  Main run `40701958830` was cancelled, then re-run: tests, publish and
  deploy-development succeeded; `/api/health` returned 200; the owner confirmed
  Save works.
- **Not demonstrated.** Automatic PR creation and auto-merge (repository
  `allow_auto_merge` is false). Obsolete `DEMO_*` variables and the
  `DEMO_CONTROL_TOKEN` secret were deleted afterwards.

### Operator tips learned

- Grafana rule labels must match the receiver contract exactly.
- To retrigger, change a rule label (for example `attempt`); the same alert
  identity is not accepted again within 30 minutes.
- The PR run only runs tests; publish/deploy happen on main after merge.
- Do not cancel the main run after merge.
