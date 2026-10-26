# Specification Approval and GitHub Enforcement

The shared [agent guard](../.github/agents/guards/specification-changes.md)
requires explicit human approval for requirement changes and independent QA/review
against the approved baseline. All four agent definitions require reading it.
These instructions are not an executable hook or a filesystem lock.

## Solo Course Project Policy

Local instructions cannot prevent file edits. The
[CODEOWNERS file](../.github/CODEOWNERS) assigns specification and guard changes to
`@sadevaraj` for ownership visibility. It is informational, not a required
code-owner approval gate, and does not itself block merges or direct pushes.

The user chose not to require another GitHub user's approval. Agents use the
owner's GitHub identity, and GitHub does not permit authors to approve their own
PRs. Do not configure required approving reviews or required code-owner reviews
for this workflow.

The coordinator still requires independent QA PASS and Reviewer-agent APPROVE
evidence. Specification changes still require explicit user approval; approval
in chat is sufficient when faithfully recorded in the issue as agent-recorded
evidence. No duplicate human confirmation on GitHub is needed.

## Remote Protection Status

No branch protection was configured by this setup. GitHub authentication has
since been restored, but no remote settings are changed by this policy update.
Do not claim the procedural guard is a hard merge lock.

PR and required CI-check rules may be considered separately once workflows exist,
without requiring another GitHub reviewer. Any remote protection changes require
authorization and verification; never configure nonexistent required check names.
