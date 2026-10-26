# Simple Sudoku

### Problem Description

Players want a straightforward way to play Sudoku, save an unfinished puzzle,
and resume later, including from another browser, using a simple account.

Simple Sudoku is a full-stack web application with username/password registration,
three predefined easy puzzles, manual progress saving, and server-side solution
checking. Each player has one game per puzzle; completed games stay read-only.
The backend stores accounts and game progress in a persistent database.

The first version targets desktop browsers and demonstrates the AI Dev Tools
Zoomcamp development workflow. The specification describes intended behaviour,
not a claim that the application has already been implemented.

### Product Specification

The authoritative [product specification](docs/specs/product.md) contains the
agreed rules, player journey, SUD-01 through SUD-14 acceptance criteria, persisted
data, and scope exclusions. Update it when requirements change with user approval,
then align the related GitHub issues and tests. Do not maintain competing copies
of the detailed requirements in the README.

The shared [agent guard](.github/agents/guards/specification-changes.md) requires
recorded human approval and independent QA/review of requirement changes.
It is an instruction, not an executable lock. CODEOWNERS is informational;
the [solo-project review policy](docs/spec-governance.md) requires independent
agent QA/review but not another GitHub user's approval.

### Agent Team Specification

Simple Sudoku uses four project-specific development agents, with
[GitHub Issues](https://github.com/sadevaraj/aidevtools_prj/issues) as their shared
task tracker.

| Agent | Responsibilities | Required output |
|---|---|---|
| [Prj_Coordinator](.github/agents/prj-coordinator.agent.md) | Clarify requirements, create authorized issues with acceptance criteria and dependencies, delegate work, route failures, and close verified issues. Does not implement application code. | Issue links, current stage, acceptance summary, and blockers |
| [Prj_Dev](.github/agents/prj-dev.agent.md) | Implement one approved issue, add developer tests, update related documentation, and fix reported defects. Does not approve or close its own work. | Implementation summary, validation results, and a DEV issue comment |
| [Prj_QA](.github/agents/prj-qa.agent.md) | Independently verify every acceptance criterion, run relevant checks, and add focused regression tests. Does not modify production code. | PASS, FAIL, or BLOCKED with per-criterion evidence in a TEST issue comment |
| [Prj_Reviewer](.github/agents/prj-reviewer.agent.md) | Independently review the tested changes for correctness, maintainability, data integrity, authorization, and scope compliance. Does not edit code. | APPROVE, CHANGES REQUESTED, or BLOCKED in a REVIEW issue comment |

#### Collaboration Process

1. The coordinator creates or refines an authorized GitHub issue with a bounded
   goal, testable acceptance criteria, and explicit dependencies.
2. Once dependencies are satisfied and implementation is authorized, the
   coordinator delegates the issue to Prj_Dev.
3. Prj_Dev implements the task, runs developer checks, and posts its evidence.
4. Prj_QA independently verifies the current changes against the issue criteria.
5. After QA passes, Prj_Reviewer reviews the same revision and change scope.
6. Failures or blocking findings return through the coordinator to Prj_Dev.
   Fixes require affected tests to be rerun and renewed review.
7. The coordinator closes the issue only after all acceptance criteria are met,
   QA passes, and the reviewer approves, with evidence recorded in the issue.

Only one writer works at a time. Workers do not delegate to one another.
Unresolved product decisions and required permissions go back to the user.
Local test results are not presented as proof of remote CI or deployment success.

The [agent team guide](.github/agents/README.md) explains how to invoke the agents;
the [delivery process](docs/process.md) defines tracker operations and evidence
formats. [AGENTS.md](AGENTS.md) links the shared project context.

These definitions describe the intended workflow, not proof it has already run.
Actual issue comments, test results, and review records provide execution
evidence. These are development agents, not the application's runtime on-call
responder.

### Course Delivery Requirements

The [architecture](docs/architecture.md) specifies separate frontend/backend
Docker images deployed on Render, a one-command local Docker Compose system
including PostgreSQL, and a single entry point for unit and integration tests.
These are agreed delivery requirements, not implemented capabilities yet.

The product specification defines the game, not the entire course submission.
The project also needs a public task tracker with acceptance criteria and evidence
of agent use, a documented agent team/process, modular project context, automated
tests, one-command local/container startup, deployment, and CI/CD.

Correlated logs, metrics, and traces are agreed scope in the
[architecture](docs/architecture.md#observability), using OpenTelemetry and a local
Grafana/Prometheus/Loki/Tempo stack. The secure destination for Render telemetry
remains to be decided. User-impact alerts and a bounded runtime on-call responder
are also approved in the [recovery plan](docs/architecture.md#user-impact-alerts-and-automatic-recovery);
the exact scenario, tools, thresholds, and hosting still need agreement.
Image rollback is already planned. None is satisfied merely by implementing the
game, and no operational implementation is claimed yet.

Course brief: https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project
