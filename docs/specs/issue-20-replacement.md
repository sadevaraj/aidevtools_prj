# Issue #20 — approved simplified save recovery

Issue: https://github.com/sadevaraj/aidevtools_prj/issues/20

## Approval, baseline and authority

Agent-recorded human chat evidence: at **2026-10-28T09:39:20Z** the user said
**“approved do it”** to the exact cleanup/replacement plan supplied again in the
current implementation handoff. This attribution is not a human-authored GitHub
comment. No approval-comment URL for this replacement was supplied; the start
report was explicitly **UNPOSTED**, because the coordinator's GitKraken comment
tool required sign-in. Do not represent that start report as tracker evidence.

Baseline: `c776c92fdf9d7d358761d47f51d3122c87904999`, deliberate save typo.
Healthy parent: `278e6116e4162e86fb7bee27295701693f5d90c3`.
Implementation belongs only in isolated branch `issue-20-simplified-recovery`,
worktree `/mnt/extra_disk/projects/course/aidevtools_prj-issue20`. The original
dirty checkout must not be changed or copied wholesale.

The current user explicitly also approved coordinator commit, push and deployment
of the **healthy simplified version to the existing Render development site**,
only after local cleanup/tests and independent current-diff QA and review PASS.
The developer must not commit, push, deploy, invoke a provider, dispatch Actions,
change settings or deploy a fault. A later fault deployment requires a separate
confirmation. No issue closure before renewed QA/review and live evidence.

## Replacement operational criteria

These replace only the operational #20 demo/fault requirements. Historical
approvals, requirement IDs and issue evidence remain historical, not completed.
Player-facing **SUD-01 through SUD-14 are unchanged**, particularly
SUD-05/06/10/12/13; migrations and account/game tables/data are untouched.

| Criterion | Required observable outcome |
|---|---|
| #20-R1 | Restore healthy `body.board` saving as approved maintenance, not a purported AI fix. Remove fault-mode jobs/dispatch, demo arm/revoke endpoints, obsolete settings and revision-pair/evidence-URL checks. Preserve normal test/build/publish and existing Render deployment pipeline. No demo/fault runtime variables or new workflow. |
| #20-R2 | Keep authenticated development Grafana webhook, durable incident deduplication/outbox, existing master `ALERT_REPAIR_ENABLED` kill switch and exact pipeline OIDC run/attempt claim. Reject invalid, expired, fabricated, replayed or unauthorized incidents; normal cookie CSRF protection remains. |
| #20-R3 | Grafana's actual **SAVE-ERROR LOG** alert sends the authenticated webhook. Restrict its log query to save server errors; no-data/query-error, resolved and expected 4xx alerts do not trigger repair. Alert payload never selects refs, commands, targets or raw diagnostic context. |
| #20-R4 | One bounded actual Copilot candidate attempt, with sanitized source/opaque incident context and isolated read/Copilot token only. No hardcoded/scripted fix masquerades as AI. Exact save-handler-only `body.borad` → `body.board` is the supported repair; unknown faults fail closed. No smoke, eligibility probe, retry loop or paid usage enablement. Entitlement/quota remain unknown unless independently verified; explicit one-attempt access-risk consent does not assert entitlement or enforce billing. No-overage and provider-transmission attestations remain mandatory. |
| #20-R5 | Execute full configured tests on the exact candidate using unchanged trusted tests, including authenticated 500/rollback and exact persisted save plus reopen. Distinct independent QA and Reviewer sessions must PASS that same patch/revision/test receipt before the isolated publisher receives its token. Publisher does not execute candidate code. |
| #20-R6 | Tested fix PR targets unchanged main. **Automatic merge AFTER ordinary PR checks is approved**, superseding manual-only merge. Bind the request to the exact PR head; never use admin/bypass/force or change protection/permissions/settings. Unavailable permissions/settings block safely and must be reported. Merge uses the ordinary main pipeline for deployment. |
| #20-R7 | Fail-stop after a single bounded attempt. Runtime stages share a server-issued maximum 15-minute claim deadline. Operator's stricter 15-minute timer starts at any separately approved future fault deployment, includes alert/queue/build/test/merge/deployment time, and ends with verified healthy restoration on failure/timeout. No autonomous rollback subsystem is introduced. |
| #20-R8 | No fault deployment, provider call, dispatch or live change in this cleanup. The intentional exact typo may only be introduced in the save handler in a later separately confirmed manually built development image outside normal test-gated CI; never a permanent alternate pipeline. Healthy restoration first. No remote CI/deployment/recovery claim from local tests. |

## Verification and dependencies

Run focused offline receiver/runner/alert/pipeline tests and `sh scripts/test.sh`
(real disposable PostgreSQL, frontend tests/build, HTTP/HTTPS proxy). Static
search must find no obsolete executable plumbing. Compare migrations and
account/game model definitions with the baseline, without touching live data.
Current independent QA then Reviewer must compare spec/guard changes and approve
the same diff. No guard changes are authorized or needed.

Issues #18/#19 supply the existing receiver/repair core. #12/#13 and remote
Grafana delivery, credentials, no-paid controls, auto-merge permission/settings,
image identity, deployed save/reopen and healthy-restoration evidence remain
live prerequisites, not local implementation blockers. Do not close this issue
or claim repository visibility/Issues status freshly verified through an
authenticated write path merely because a read or a local test succeeds.

Important future-run boundary: healthy main contains no typo, so an image-only
fault with unchanged healthy source cannot honestly produce a corrective source
PR. The runner must stop on an empty/unsupported source patch. The coordinator
must resolve source/image provenance for any future separately confirmed fault
exercise; this cleanup neither creates such a fault nor invents an AI repair.
