# Simple Sudoku Agent Team

| Agent | Responsibility |
|---|---|
| [Prj_Coordinator](prj-coordinator.agent.md) | Clarify requirements, maintain GitHub Issues, delegate tasks, and close verified work |
| [Prj_Dev](prj-dev.agent.md) | Implement one approved issue, including developer tests and relevant documentation |
| [Prj_QA](prj-qa.agent.md) | Independently verify acceptance criteria and add focused regression tests |
| [Prj_Reviewer](prj-reviewer.agent.md) | Independently review changes after testing and report blocking findings |

Select **Prj_Coordinator** in the VS Code agent picker. For example:

> Read the Sudoku specification and propose the initial GitHub Issues backlog.
> Ask about unresolved architecture choices before creating implementation tasks.

To authorize tracker creation:

> Create the agreed backlog as GitHub Issues. Do not start implementation.

To authorize execution:

> Work on issue #N through development, independent testing, and review.

Agents read [AGENTS.md](../../AGENTS.md) and follow the shared
[delivery process](../../docs/process.md). Workers do not delegate to each other.
The coordinator routes failures back to development.

## Shared Guards

Every agent must explicitly read
[guards/specification-changes.md](guards/specification-changes.md) before work.
It defines the approval and review gates once for reuse across the team.
The guards folder is not automatically loaded and contains instructions, not
executable hooks. See [GitHub enforcement](../../docs/spec-governance.md) for the
separate remote protection status.

## Configuration Notes

These files use the documented VS Code custom-agent format. Model selection is
left to the user's agent settings. Tool lists are omitted so the selected harness
can supply its available GitHub, execution, and delegation tools. Role boundaries
in the instructions are behavioural constraints, not a filesystem or shell
sandbox. Reviewers may use GitHub commands to post findings but must not edit code.

GitHub access must be authenticated and permitted; instructions cannot grant it.
These are development agents, not the application's runtime on-call responder.

## Sources

The definitions are project-specific, based on official configuration guidance,
not copied third-party agent bodies. There is no universally best agent template.

- [VS Code custom agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents)
- [GitHub custom agents configuration](https://docs.github.com/en/copilot/reference/custom-agents-configuration)
- [Course project requirements](https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project)
