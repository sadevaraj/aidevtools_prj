# GitHub Issues Delivery Process

## Tracker and Access

Use [GitHub Issues](https://github.com/sadevaraj/aidevtools_prj/issues), not a local
task file, as the authoritative delivery backlog. A Projects board is optional.
Before first use, verify authenticated access, repository identity, Issues enabled,
and public visibility. A private tracker does not meet the public-access criterion.
Do not change visibility or repository settings without explicit authorization.

Prefer the authenticated `gh` CLI. For example:

```sh
gh auth status
gh repo view sadevaraj/aidevtools_prj --json nameWithOwner,isPrivate,hasIssuesEnabled
gh issue list --repo sadevaraj/aidevtools_prj --state open --limit 50
gh issue view N --repo sadevaraj/aidevtools_prj --comments
```

`N` is a placeholder for the assigned issue number. Never paste tokens into
tracked files. If access fails, report BLOCKED with the error and required action.
Do not substitute a local report while claiming a public comment was posted.

## Issue Template

The coordinator checks for duplicates and obtains authorization before creating
the agreed backlog. Every task uses:

```markdown
## Goal
One bounded outcome, linked to relevant SUD requirement IDs in docs/specs/product.md.

## Scope
Included behaviour, exclusions, and constraints.

## Acceptance criteria
- [ ] Observable and independently verifiable behaviour.
- [ ] Relevant failure and authorization cases.

## Dependencies
Issue links, or "None".

## Verification
Required automated/manual checks and expected outcomes.
```

Create real dependency issues first, then link them. Do not assume issue-number
order implies dependencies. Do not create a fictional completed backlog or
fabricate past agent activity.

## Workflow

Read the [product specification](specs/product.md) before defining or executing a
task. Behaviour changes require user approval and an updated specification,
followed by aligned issue criteria and tests. Never rewrite requirements merely
to make an implementation pass.

Read and follow the
[shared specification guard](../.github/agents/guards/specification-changes.md)
before work and for any requirement change.
Every handoff identifies the task's base revision and approved specification.
QA and Reviewer must compare specification/guard changes against that baseline
and report missing human approval as blocking. The coordinator cannot close the
issue until approval evidence and renewed verification are recorded. Explicit
user approval in chat is sufficient when recorded as specified in the guard.
Independent QA and agent review remain required; another GitHub user's approval
or a GitHub code-owner approving review is not required.

1. **READY:** criteria are agreed and dependencies are closed with evidence.
2. **DEV:** coordinator posts a start comment and delegates to Prj_Dev.
3. **TEST:** Prj_Dev posts its report; Prj_QA independently verifies current work.
4. **REVIEW:** after TEST PASS, Prj_Reviewer reviews the same revision and diff.
5. **FIX:** failures route through the coordinator to Prj_Dev. Changed code receives
   affected test reruns and renewed review; stale evidence does not count.
6. **DONE:** coordinator posts the final acceptance summary and closes the issue
   only after all criteria, TEST PASS, and REVIEW APPROVE are recorded.

Use issue comments for stages; labels and Projects automation are optional.
Do not use automatic issue-closing PR keywords before the acceptance gates are met.
Workers do not close issues. Do not claim deployment criteria passed from local
test results. Where remote CI or deployed checks are required, record their links.

## Evidence Report

Each worker posts a comment to the assigned issue using `gh issue comment` (or an
available authenticated GitHub tool), with:

- Role and verdict: DEV READY FOR TEST; TEST PASS/FAIL/BLOCKED; REVIEW
  APPROVE/CHANGES REQUESTED/BLOCKED.
- Issue and relevant acceptance criteria.
- Revision and uncommitted diff scope, if applicable.
- Changes or per-criterion results.
- Exact commands executed and their outcomes, distinguishing NOT RUN.
- Reproduction steps and blocking findings.
- Relevant PR, CI, deployment, and prior evidence links.
- Specification/guard diff result and human approval link for any changes, or
  explicitly "No specification or guard changes."
- Limitations and next action.

For example, write a report with `gh issue comment N --repo
sadevaraj/aidevtools_prj --body-file <report-path>`. Use a session-local temporary
report file, not an unnecessary tracked status file. Confirm the posted comment
URL before reporting success. Exclude credentials and sensitive logs.

Instructions alone are not course evidence: real tasks and real agent comments
must be visible publicly. These development agents do not implement the runtime
on-call responder criterion; that needs its own agreed design and verification.
