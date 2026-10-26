# Guard: Specification Changes

Read and apply this guard before planning, implementing, testing, or reviewing
work. It is a shared instruction, not an executable hook or technical lock.
The containing folder is not automatically loaded by Copilot; agent definitions
explicitly require reading this file.

## Source of Truth

Use the specification identified in the repository's
[project context](../../../AGENTS.md). For this project it is
[docs/specs/product.md](../../../docs/specs/product.md).
For reuse in another repository, update these project references.

Do not change specifications, weaken issue acceptance criteria, remove tests,
or alter safeguards merely to make an implementation pass. If implementation
conflicts with requirements, report the conflict and request a human decision.

## Approval Gate

1. The coordinator describes old and proposed behaviour, affected requirement
   IDs, rationale, and impact on tests and existing data.
2. Obtain explicit human approval for that exact proposal before editing the
   specification or implementing the changed behaviour. General authorization to
   implement a feature does not authorize changing its requirements.
3. Record the owner's issue-comment URL or an attributed excerpt and date of
   explicit approval in this chat. Post chat evidence in the issue and label it
   agent-recorded. No second GitHub account, GitHub approving review, or duplicate
   confirmation on GitHub is required. Never invent approval or describe an
   agent-authored comment as a comment posted by the human.
4. Update the specification, issue criteria, and tests consistently. Include
   approval evidence and affected requirement IDs in the PR description.
5. Changed proposals require renewed approval. Formatting-only corrections do
   not require behavioural approval.

## Role Gates

- **Coordinator:** provide the task base revision and approved specification in
  handoffs. Do not close or authorize merge with missing approval evidence.
- **Developer:** preserve approved requirements. Report any specification or
  guard changes with approval evidence; otherwise state that none changed.
- **QA:** compare specifications, issue criteria, and guards against the task
  baseline, including deletions and renames. Missing approval blocks acceptance,
  even when tests pass. Verify aligned tests after approved changes.
- **Reviewer:** independently repeat that comparison and block unapproved changes
  or weakened safeguards. Check evidence covers the current revision.

If evidence or the baseline is unavailable, report BLOCKED rather than guessing.
Independent QA and Reviewer-agent reports are required by the delivery process.
They do not replace the user's approval of requirement changes, but no human
GitHub code-owner review is required for this solo course project.

See [GitHub enforcement status](../../../docs/spec-governance.md) for the separate
remote merge safeguards and their limitations.
