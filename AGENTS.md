# Simple Sudoku Project Context

## Sources of Truth

- [README.md](README.md): project overview and agent team.
- [Product specification](docs/specs/product.md): agreed behaviour and SUD acceptance
  criteria. Read this before planning, implementing, testing, or reviewing a feature.
- [Architecture](docs/architecture.md): agreed stack, image-based Render deployment,
  local Docker Compose setup, testing requirements, and unresolved technical choices.
- [GitHub Issues](https://github.com/sadevaraj/aidevtools_prj/issues): authoritative
  public task tracker once availability and visibility are verified.
- [Delivery process](docs/process.md): tracker operations and quality gates.
- [Shared agent guard](.github/agents/guards/specification-changes.md): read before
  work; defines human approval evidence and specification-change review gates.
- [GitHub enforcement](docs/spec-governance.md): remote protection status and setup.
- [Agent team](.github/agents/README.md): roles, usage, and configuration sources.

The log-analyser material in plan.md is superseded and must not drive Sudoku work.
Follow the agreed architecture; ask about its remaining unresolved details rather
than inventing decisions.

## Working Rules

- Read the assigned issue and dependencies before implementing. Ask about
  significant unresolved requirements rather than silently making product choices.
- Use Prj_Coordinator -> Prj_Dev -> Prj_QA -> Prj_Reviewer. Failures return through
  the coordinator. Keep one writer active at a time.
- Preserve unrelated work. Make scoped changes with tests and related documentation.
- Never change specifications, weaken acceptance criteria, or alter these guards
  to make implementation pass. Read and follow
  .github/agents/guards/specification-changes.md: obtain explicit
  human approval, record evidence, and block acceptance of unapproved changes.
- Use existing configured validation commands once the stack is established.
  Never report commands, CI, tracker writes, or deployments as successful without
  actual evidence.
- Use authenticated GitHub tooling without exposing secrets. Do not create,
  overwrite, print, or commit tokens or credentials to enable access.
- Do not commit, push, deploy, or change remote settings without explicit
  authorization. Report access problems rather than bypassing permissions.
- Agent files guide behaviour; they do not enforce a security sandbox.
