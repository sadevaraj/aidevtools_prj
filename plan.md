# Simple Sudoku: Approved Simplified Recovery Plan

## Current plan — user-approved replacement, 28 October 2026

At **2026-10-28T09:39:20Z**, the user said **“approved do it”** to the exact
cleanup/replacement recorded in [issue #20 replacement specification](docs/specs/issue-20-replacement.md).
This agent-attributed chat approval supersedes the earlier operational #19/#20
plans. Their obsolete recovery/demo procedures are removed, not retained as an
archival how-to. No GitHub approval-comment URL is invented.

1. Restore healthy saving locally as maintenance. Remove obsolete fault/demo
   paths; preserve migrations, account/game data, SUD-01..14, normal tests/build/
   publish and existing opt-in Render development deployment.
2. Keep the authenticated SAVE-ERROR LOG webhook, durable dedup/outbox, existing
   repair kill switch and exact one-time OIDC run/attempt claim.
3. Keep one actual bounded isolated Copilot candidate attempt, no smoke/probe/
   retries or paid enablement. Unsupported faults stop, never a scripted fix.
4. Require full exact-candidate tests, exact persistence/reopen and independent
   same-candidate QA/Reviewer evidence before isolated PR publication.
5. Request automatic merge only AFTER ordinary PR checks with exact-head match;
   never bypass protection/permissions or modify remote settings. Existing main
   pipeline deploys after merge. Missing technical permissions/settings block.
6. Require operator healthy restoration within 15 minutes from any future
   separately confirmed fault deployment. Current cleanup does no live action.
   The coordinator may commit/push/deploy only the healthy version after renewed
   independent QA/review PASS; no fault deployment/provider/dispatch is approved.

See the current [architecture](docs/architecture.md) and
[runbook](docs/runbooks/development-save-demo.md). Existing source/image
provenance and live evidence limitations are explicit there. This is not a
claim of live recovery or completion; #20 stays open.

---

## Future fault exercise — BLOCKED

An image-only `body.board` → `body.borad` fault with healthy repository `main`
cannot by itself yield a corrective source PR: the source has no typo to repair.
An empty or unsupported source patch must fail closed, not be presented as an
AI repair. Any actual future fault exercise remains blocked pending a separate
owner decision on source/image provenance and explicit confirmation. This plan
does not invent a solution or authorize a fault deployment, provider call,
dispatch or live change.

---

# Historical Project Direction: Superseded

The project changed to **Simple Sudoku** on 26 October 2026. The current
Problem Description and Product Specification are in
[docs/specs/product.md](docs/specs/product.md), with an overview in
[README.md](README.md).
All log-analyser requirements and delivery steps below are historical reference,
not the current implementation plan. The approved Sudoku replacement above
does not approve the historical requirements below.

---

# AI Incident Analyser: Agreed Problem and Initial Specification

## Planning Status

This historical section records the requirements discussed on 26 October 2026.
It was the planning baseline for the superseded incident-analyser direction,
not the current Sudoku baseline or authorization for new work.

- First submission: a working application by **11 PM on 26 October 2026**.
  The deadline timezone and submission instructions still need confirmation.
- Improvements can follow before the next submission deadline; that date is not
  yet recorded.
- Implementation has not been requested as part of this requirements discussion.
- Course reference: https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project

## Agreed Problem

The Kanban board is an existing application completed during the course. This
project must be a new application demonstrating the development and operational
concepts learned while building it.

The new application will help an operator investigate and recover from a failure
in that Kanban application. It will turn failure evidence into a visible incident,
use a hosted AI model to explain the evidence, and trigger one explicitly permitted
recovery action. It must verify recovery rather than assume that a successful
action means the user-facing problem has been fixed.

The operator persona is a working assumption to refine, not a confirmed multi-user
product requirement.

## Confirmed Decisions

| Area | Decision |
|---|---|
| New project | A full-stack incident analyser, separate from the completed Kanban application |
| Monitored target | The existing Kanban application |
| Core workflow | Detect failure -> explain with AI -> perform bounded recovery -> verify |
| AI | A hosted model on a free tier only; provider, model, credentials, and limits remain open |
| Deployment | Render |
| Database budget | Avoid a paid database |
| Database direction | Investigate sharing the existing Render PostgreSQL instance with Kanban |
| Demonstration | A controlled fault in staging/demo makes an important operation fail; an allow-listed action disables the fault and the operation is retried |
| Safety boundary | Do not deliberately break production or let the model execute arbitrary code |
| Deferred features | RAG and general-purpose code repair are not initial requirements |

## Kanban Inspection and Proposed Demonstration

The user identified the existing project at
`/mnt/extra_disk/projects/course/aidevtools_hw2` and requested a recommendation
after inspection. No hosted-model provider has been selected or configured.

Read-only inspection found:

- A FastAPI backend with a WebSocket endpoint at `/ws`.
- The connection handler sends an initial `snapshot` containing board data.
- `/health` currently returns a static `{"status": "ok"}` response; it is not
  evidence that a user can load the board.
- The backend documents PostgreSQL configuration for Render.
- A local observability stack already exists with OpenTelemetry Collector,
  Prometheus, Loki, Tempo, and Grafana. This is useful prior art, not proof that
  the new application's deployed telemetry is complete.

**Recommendation, pending user approval:** monitor loading the board through
the real WebSocket snapshot flow. A synthetic client connects and expects a
valid snapshot within a defined timeout. This exercises a real read path without
creating synthetic tasks or needing cleanup.

Introduce a demo/staging-only, authenticated fault control that prevents this
flow from succeeding. The permitted responder action disables only that fault.
Verification opens a new connection and validates the snapshot again.
The exact fault mechanism must be designed before implementation; it does not
currently exist based on the inspected flow.

The deployed Kanban URL, staging availability, and permission for these changes
remain partly unconfirmed. The user permits planned Kanban changes only in a
separate demo/staging deployment, not production. The user requested an
explanation before approving the board-loading scenario. No implementation is
authorized by this planning discussion.

## Initial Product Specification

### Main User Journey

1. An operator enables a controlled, demo-only fault in Kanban.
2. A real request to an important Kanban operation fails.
3. Monitoring detects the failed operation and creates a persistent incident.
4. A user-impact alert triggers the responder workflow.
5. A hosted model explains the available evidence. The dashboard distinguishes
   the explanation from verified facts.
6. The responder invokes only the permitted action to disable the demo fault.
7. The same operation is retried against the monitored application.
8. The incident is resolved only when the operation succeeds; otherwise it remains
   unresolved and the failure is visible.
9. The dashboard shows the evidence, diagnosis, action, verification, and timeline.

### Draft Acceptance Criteria

These criteria translate the agreed workflow into testable behaviour. Exact
thresholds and interface details must be settled before their implementation.

- The new frontend communicates with its backend, and incidents and recovery
  results persist in PostgreSQL.
- A controlled failure of the selected Kanban operation creates a visible
  incident and triggers the responder without an operator manually starting it.
- Repeated observations of the same active failure update that incident rather
  than generating an unbounded stream of duplicate incidents or recovery actions.
- The hosted-model explanation is stored with the incident and its evidence.
  Model errors are shown explicitly, not replaced with a fabricated diagnosis.
- Recovery is restricted to the selected staging/demo fault. Unknown failures
  cannot cause arbitrary shell execution, source changes, or production changes.
- The responder has a finite attempt limit. Failed or exhausted recovery attempts
  are recorded and require operator attention.
- Resolution requires a successful retry of the selected user-facing operation,
  not merely a process-health check or an action returning success.
- A failed verification leaves the incident unresolved and visible.
- Credentials and customer data are excluded from telemetry and model inputs.

### Out of Initial Scope

- General-purpose generated code patches, autonomous PRs, or an AI code reviewer.
- RAG, vector search, Qdrant, local embeddings, and Ollama.
- Unrestricted remediation or deliberate production failure injection.
- Multiple monitored applications.
- The extensive approval/deployment management UI described in the earlier proposal.

## Shared Database Proposal

One PostgreSQL instance can host data for both applications. This is a proposed
cost-saving arrangement, not a verified Render configuration.

- Use separate application schemas and migration histories.
- Prefer separate least-privilege roles where the provider permits them.
- Do not reuse or modify Kanban business tables as analyser storage.
- Verify available connections, storage, access restrictions, and database expiry.
- Sharing an instance does not extend a free plan's lifetime.
- Both applications share a database failure domain. The initial recovery
  demonstration therefore targets an application fault, not a database outage.
- SQLite is not the selected deployment solution. It would require a verified
  persistent-storage arrangement; an ephemeral deployment filesystem is not
  sufficient for durable incident history.

## Course Requirements and Evidence Plan

The idea can cover every rubric category, but the evidence must actually be built
and demonstrated. This table is a checklist, not a claim of completion.

| Criterion | Planned evidence |
|---|---|
| Problem description | README explaining the user problem, functionality, and expected behaviour |
| Product specification | Written specification and public task tracker with acceptance criteria and evidence of agent use |
| Agent team | Defined responsibilities and collaboration process |
| Context management | AGENTS.md linking to modular project/process documentation |
| Application | Connected frontend, backend, and persistent database; one-command local startup |
| Testing | Unit and integration tests passing with one command, plus frontend coverage for the main journey |
| Containerization | Full local system, including database, starts with one Docker Compose command |
| Deployment | Reachable Render deployment or clear deployed demonstration |
| CI/CD | PR tests, automated deployment, and a rollback path; dev deployment with manual production promotion is the higher-scoring target |
| Observability | Metrics, traces, and structured logs for a key journey, sharing a trace ID and collected/stored/viewable in a UI |
| User-impact alerting | Alert based on failure of the selected Kanban operation |
| On-call agent | Alert wakes a responder, which performs the bounded fix and verifies recovery |

The course also requires reviewing three other participants' projects.
Its brief suggests roughly 20 hours, but today's available implementation time has
not been estimated. Full rubric coverage must not be promised merely from the plan.

## Delivery Order for Today's Working Submission

1. Confirm access to Kanban, its deployment, and the shared database; select the
   operation and safe fault/recovery interface.
2. Establish the public task tracker and acceptance criteria before writing code.
3. Build one connected frontend/backend/database slice for incident viewing.
4. Connect real failure detection and persist an incident from Kanban.
5. Add the hosted-model diagnosis with explicit error reporting.
6. Connect the alert to the bounded recovery action and verify the real operation.
7. Test the critical success and failure paths, containerize, and deploy.
8. Document reproducible setup/demo instructions and truthfully identify missing
   rubric evidence for the later submission.

Telemetry, tests, and safety checks should be added alongside the relevant slice,
not postponed until an otherwise complete platform exists.

## Decisions Still to Discuss

- Kanban repository, stack, public URL, and permission to change its demo/staging
  deployment.
- The exact operation to monitor, injected fault, and authenticated recovery action.
- Detection interval, alert threshold, deduplication window, recovery attempt limit,
  verification timeout, and responder behaviour when the model is unavailable.
- Hosted-model provider, credentials, and spending limit.
- Existing Render database capacity/expiry and support for schema/role isolation.
- Authentication for the dashboard, fault trigger, and responder.
- Telemetry collection/storage/UI and how the alert wakes the responder.
- Render service layout, CI/CD workflow, rollback mechanism, and environment
  separation.
- Today's submission instructions, timezone, and next deadline.

---

## Superseded Proposal: Reference Only

The material below preserves the original brainstorming for possible later use.
Its local-model stack, RAG, autonomous patching, broad dashboard, weekend schedule,
and larger delivery commitments are **not approved current scope**.

### Original Title: AI Log Analyser and Self-Healing Deployment Platform

## 1. Project Summary

Build a full-stack AI-assisted operations platform that monitors the existing Kanban board application, detects failures from logs, explains likely causes, searches local project knowledge, proposes controlled fixes, runs automated checks, deploys approved changes, and verifies system health after deployment.

The project contains two applications:

1. **Existing Kanban board**: the monitored production application and controlled failure target.
2. **AI Log Analyser**: a new full-stack application with its own frontend, backend, database, tests, CI/CD pipeline, production deployment, monitoring, and notifications.

The first version must be safe and auditable. It must not blindly change production. Every proposed change must be stored in Git and pass defined quality gates before deployment.

---

## 2. Project Goals

- Build a complete frontend and backend application.
- Store logs, incidents, analyses, deployment results, and audit history.
- Monitor the deployed Kanban board.
- Detect and group meaningful application errors.
- Use a local large language model to explain failures in plain language.
- Use retrieval-augmented generation (RAG) to search local documentation, source code, deployment files, and previous incidents.
- Notify the user when a problem is detected.
- Generate a proposed fix for selected, low-risk failure types.
- Review proposed code changes before they are accepted.
- Run unit, integration, security, and health checks.
- Deploy safely through a CI/CD pipeline.
- Verify the application after deployment.
- Roll back or stop when verification fails.
- Provide a clear dashboard showing every decision and action.

---

## 3. Non-Goals for the MVP

The first version will not:

- Give an AI agent unrestricted production access.
- Automatically merge every proposed change.
- Attempt to fix unknown or high-risk incidents.
- Modify infrastructure, credentials, database schemas, or security settings without approval.
- Replace normal logging, monitoring, testing, or code review tools.
- Train a new large language model.
- Support many unrelated applications.

---

## 4. High-Level Architecture

```text
                        +-----------------------+
                        |   Log Analyser UI     |
                        | React / TypeScript    |
                        +-----------+-----------+
                                    |
                                    | REST / WebSocket
                                    v
+----------------+       +----------+-----------+       +----------------+
| Kanban Board   | ----> | Log Analyser API     | ----> | PostgreSQL     |
| Production App | logs  | FastAPI / Python     |       | incidents,     |
+-------+--------+       +----+----------+-------+       | logs, audit    |
        |                     |          |               +----------------+
        | health              |          |
        | checks              |          +----------------------+
        v                     v                                 v
+-------+--------+     +------+-------------+          +--------+---------+
| Monitoring     |     | Local AI / Ollama  |          | Qdrant          |
| and Collector  |     | analysis and patch | <------> | RAG vectors     |
+----------------+     +------+-------------+          +------------------+
                              |
                              v
                       +------+-------------+
                       | Git branch / PR    |
                       +------+-------------+
                              |
                              v
                       +------+-------------+
                       | CI quality gates   |
                       +------+-------------+
                              |
                              v
                       +------+-------------+
                       | Staging deployment |
                       +------+-------------+
                              |
                              v
                       +------+-------------+
                       | Production + verify|
                       +--------------------+
```

---

## 5. Proposed Technology Stack

### Frontend

- React
- TypeScript
- Vite
- A lightweight component library or plain CSS
- WebSocket or Server-Sent Events for live status updates
- Vitest and React Testing Library
- Playwright for end-to-end tests

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic database migrations
- WebSocket or Server-Sent Events
- Pytest

### Data and AI

- PostgreSQL for application data
- Qdrant for vector search
- Ollama for running a local model
- `sentence-transformers` for local embeddings
- Structured JSON output from the model

### DevOps

- Git
- Docker and Docker Compose
- CI/CD using the platform already used by the Kanban project
- Staging and production environments
- Automated health checks
- Versioned container images
- Rollback to the last known healthy version

### Observability and Notifications

- Structured JSON logs
- Application health endpoint
- Notification-channel options in this superseded proposal are not part of
  the current Sudoku plan; use the authenticated webhook flow above.
- Correlation ID for every incident and fix attempt

---

## 6. Core User Stories

### Monitoring

- As an operator, I want the system to collect Kanban application logs so that failures can be detected.
- As an operator, I want repeated copies of the same error grouped into one incident so that alerts remain useful.
- As an operator, I want to see whether the Kanban frontend, backend, and database are healthy.

### AI Analysis

- As an operator, I want a plain-language explanation of an incident.
- As an operator, I want the system to show the exact evidence used for its diagnosis.
- As an operator, I want relevant documentation, code locations, configuration, and previous incidents retrieved through RAG.
- As an operator, I want uncertainty clearly shown rather than hidden.

### Controlled Remediation

- As a developer, I want the system to propose a patch in a separate Git branch.
- As a reviewer, I want to see the diff, explanation, retrieved evidence, test results, and risk level.
- As an operator, I want normal fixes to require approval during the MVP.
- As an operator, I want only explicitly allow-listed low-risk fixes to be eligible for automatic staging deployment.

### Deployment

- As a developer, I want every proposed fix to run through CI.
- As an operator, I want a successful build deployed to staging before production.
- As an operator, I want post-deployment health checks to confirm that the incident is resolved.
- As an operator, I want deployment stopped or rolled back when verification fails.

### Auditability

- As an operator, I want a complete timeline of detection, analysis, approval, tests, deployment, and verification.
- As a developer, I want to know which model, prompt version, documents, and application version were used.

---

## 7. Functional Requirements

### 7.1 Log Collection

The analyser shall:

- Accept logs through an authenticated HTTP endpoint.
- Support log-file import for demonstrations and testing.
- Ingest structured logs from the Kanban backend.
- Record timestamp, service, environment, severity, message, stack trace, application version, and correlation ID when available.
- Reject oversized or malformed payloads.
- Mask configured secrets before storage or AI processing.
- retain raw logs separately from normalised incident data.

### 7.2 Incident Detection

The analyser shall:

- Detect configured error patterns.
- Group similar events into one incident.
- Track first seen, last seen, occurrence count, service, environment, and status.
- Assign an initial severity using deterministic rules.
- Prevent notification storms through deduplication and cooldown rules.
- Allow incidents to be opened, acknowledged, resolved, or dismissed.

### 7.3 RAG Search

The RAG service shall index selected local content:

```text
kanban-project/
├── README.md
├── docs/
├── backend/
├── frontend/
├── deployment/
├── tests/
└── troubleshooting/

log-analyser/
├── docs/
├── runbooks/
└── previous-incidents/
```

The RAG pipeline shall:

- Scan only configured folders.
- Respect ignore rules for secrets, build outputs, virtual environments, dependencies, and generated files.
- Chunk documents with source metadata.
- Store embeddings in Qdrant.
- Return the source file and relevant passage for each result.
- Re-index changed files incrementally.
- Avoid sending secrets or binary content to the model.

### 7.4 AI Incident Analysis

The AI service shall return a validated structure similar to:

```json
{
  "summary": "Kanban backend cannot connect to PostgreSQL",
  "category": "configuration",
  "severity": "high",
  "probable_cause": "Configured database port does not accept connections",
  "evidence": [
    "Connection refused during application startup"
  ],
  "affected_component": "backend",
  "suggested_actions": [
    "Verify that PostgreSQL is running",
    "Check the configured database host and port"
  ],
  "confidence": 0.88,
  "automatic_fix_eligible": false
}
```

The backend shall validate this output. Invalid model output must not trigger automation.

### 7.5 Dashboard

The frontend shall provide:

- Overall Kanban application health.
- Latest deployed version.
- Active and resolved incidents.
- Filterable log view.
- Incident detail page.
- AI diagnosis and confidence.
- Retrieved RAG evidence with file paths.
- Proposed Git diff.
- Code-review findings.
- Test and pipeline status.
- Deployment progress.
- Post-deployment verification result.
- Complete audit timeline.
- Controls for approve, reject, retry analysis, deploy to staging, and roll back when authorised.

### 7.6 Notifications

Notifications shall include:

- Incident ID.
- Affected service and environment.
- Severity.
- Short description.
- Detection time.
- Link or identifier for opening the incident dashboard.
- Current remediation status.

Notifications must be deduplicated and must not contain secrets or full stack traces.

### 7.7 Patch Generation

For selected incidents, the system may:

- Create a dedicated Git branch.
- Supply the incident, retrieved evidence, and relevant source files to the agent.
- Restrict writable files using an allow-list.
- Generate a minimal patch.
- Record the generated diff.
- Refuse changes outside the allowed scope.
- Never commit secrets.

Initially, patch generation should target controlled failures created specifically for the course demonstration.

### 7.8 Code Review

The reviewer shall check:

- Whether the patch addresses the detected incident.
- Whether unrelated files were changed.
- Error handling.
- Security-sensitive changes.
- Missing or weakened tests.
- Configuration and secret exposure.
- Change size and risk.

A reviewer finding must block automatic deployment when its configured severity is high.

### 7.9 CI/CD and Deployment

The pipeline shall run:

1. Formatting check.
2. Static analysis or linting.
3. Backend unit tests.
4. Frontend unit tests.
5. Integration tests.
6. Dependency and secret scanning where available.
7. Container build.
8. Staging deployment.
9. Staging smoke test.
10. Production approval or allow-listed automatic promotion.
11. Production deployment.
12. Post-deployment health verification.
13. Rollback or stop on failure.

---

## 8. Safety Rules

- Production credentials must never be provided to the language model.
- The model must not execute arbitrary shell commands.
- Tools exposed to an agent must be explicit and allow-listed.
- The agent must not directly push to the protected main branch.
- Every generated change must be visible in Git.
- Database migrations, authentication, authorisation, secrets, and infrastructure changes always require human approval.
- Automatic remediation is initially enabled only in staging.
- Production automation is enabled only for demonstrated, allow-listed scenarios.
- The system must stop after a configured number of failed fix attempts.
- The system must never create an endless analyse-fix-deploy loop.
- A failed health check must trigger rollback or manual intervention, not another blind production change.

---

## 9. Data Model

Suggested primary entities:

### `services`

- `id`
- `name`
- `environment`
- `health_url`
- `repository_path`
- `current_version`

### `log_events`

- `id`
- `service_id`
- `timestamp`
- `severity`
- `message`
- `stack_trace`
- `correlation_id`
- `application_version`
- `fingerprint`

### `incidents`

- `id`
- `service_id`
- `title`
- `status`
- `severity`
- `first_seen`
- `last_seen`
- `occurrence_count`
- `fingerprint`

### `analyses`

- `id`
- `incident_id`
- `summary`
- `probable_cause`
- `evidence`
- `suggested_actions`
- `confidence`
- `model_name`
- `prompt_version`
- `created_at`

### `retrieved_sources`

- `id`
- `analysis_id`
- `file_path`
- `chunk_reference`
- `relevance_score`

### `fix_attempts`

- `id`
- `incident_id`
- `branch_name`
- `commit_id`
- `diff_summary`
- `risk_level`
- `approval_status`
- `created_at`

### `pipeline_runs`

- `id`
- `fix_attempt_id`
- `status`
- `test_summary`
- `image_version`
- `started_at`
- `completed_at`

### `deployments`

- `id`
- `pipeline_run_id`
- `environment`
- `version`
- `status`
- `health_check_result`
- `rollback_version`
- `deployed_at`

### `audit_events`

- `id`
- `incident_id`
- `actor_type`
- `action`
- `details`
- `timestamp`

---

## 10. API Outline

```text
POST   /api/v1/logs
GET    /api/v1/logs
GET    /api/v1/health/services
GET    /api/v1/incidents
GET    /api/v1/incidents/{incident_id}
POST   /api/v1/incidents/{incident_id}/analyse
POST   /api/v1/incidents/{incident_id}/acknowledge
POST   /api/v1/incidents/{incident_id}/resolve
POST   /api/v1/incidents/{incident_id}/propose-fix
POST   /api/v1/fixes/{fix_id}/approve
POST   /api/v1/fixes/{fix_id}/reject
POST   /api/v1/fixes/{fix_id}/deploy-staging
POST   /api/v1/deployments/{deployment_id}/promote
POST   /api/v1/deployments/{deployment_id}/rollback
GET    /api/v1/pipelines/{pipeline_id}
GET    /api/v1/audit
GET    /api/v1/events/stream
```

---

## 11. Repository Structure

```text
ai-log-analyser/
├── frontend/
│   ├── src/
│   ├── tests/
│   ├── Dockerfile
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── log_ingestion/
│   │   │   ├── incident_detection/
│   │   │   ├── rag/
│   │   │   ├── ai_analysis/
│   │   │   ├── git_operations/
│   │   │   ├── code_review/
│   │   │   ├── deployment/
│   │   │   └── notifications/
│   │   └── main.py
│   ├── tests/
│   ├── migrations/
│   ├── Dockerfile
│   └── pyproject.toml
├── collector/
│   ├── app/
│   ├── tests/
│   └── Dockerfile
├── docs/
│   ├── architecture.md
│   ├── threat-model.md
│   ├── runbooks/
│   └── demo-scenarios.md
├── scripts/
│   ├── index_knowledge.py
│   ├── inject_failure.py
│   └── verify_deployment.py
├── deployment/
│   ├── docker-compose.yml
│   ├── staging/
│   └── production/
├── .github/workflows/ or equivalent-ci-directory/
├── .env.example
├── AGENTS.md
├── README.md
└── plan.md
```

---

## 12. Implementation Phases

## Phase 0: Confirm Existing Kanban Interface

- Identify the Kanban frontend, backend, database, and deployment environments.
- Confirm where backend and deployment logs can be obtained.
- Add a version endpoint if one does not exist.
- Add a health endpoint if one does not exist.
- Add structured application logging.
- Select safe failure scenarios.
- Document all credentials and secrets that must be excluded.

**Done when:** the deployed Kanban application exposes health/version information and produces usable structured logs.

## Phase 1: Create the Full-Stack Log Analyser Skeleton

### Backend

- Create FastAPI project.
- Add PostgreSQL connection.
- Add migrations.
- Add service, log-event, and incident models.
- Add health endpoint.
- Add API documentation.

### Frontend

- Create React/TypeScript project.
- Add application shell and navigation.
- Add system-health, incidents, logs, and settings pages.
- Connect frontend to backend.

### Deployment

- Add Dockerfiles.
- Add Docker Compose for local development.
- Add environment templates.
- Add basic CI for linting, tests, and builds.

**Done when:** the frontend and backend run locally, store data, pass CI, and can be deployed as containers.

## Phase 2: Log Ingestion and Incident Detection

- Add protected log-ingestion API.
- Create a small Kanban log forwarder or collector.
- Normalise incoming events.
- Mask secrets.
- Create deterministic incident fingerprints.
- Group repeated events.
- Add active/resolved incident views.
- Add notification deduplication.

**Done when:** a controlled Kanban failure creates one visible incident and one notification.

## Phase 3: AI Analysis

- Integrate Ollama.
- Define a strict response schema.
- Create an analysis prompt.
- Validate model output.
- Store analysis and model metadata.
- Show diagnosis, evidence, suggested actions, and confidence in the UI.
- Add fallback behaviour when the model is unavailable.

**Done when:** an operator can request an AI analysis of an incident and see a stored, validated result.

## Phase 4: Local-Folder RAG

- Configure allowed folders.
- Add ignore rules.
- Create document loaders and chunking.
- Generate local embeddings.
- Store vectors in Qdrant.
- Add incremental indexing.
- Retrieve relevant material for an incident.
- Show source files and excerpts in the UI.
- Include retrieved evidence in the AI analysis.

**Done when:** a known failure retrieves the correct runbook or source area and uses it in the diagnosis.

## Phase 5: Proposed Fix and Code Review

- Define the safe patch-generation scope.
- Create a Git branch for each fix attempt.
- Provide only relevant, allowed files to the agent.
- Generate a minimal patch.
- Reject modifications outside the allow-list.
- Add an independent AI review step.
- Run deterministic static checks.
- Show the diff and review findings in the UI.
- Require human approval.

**Done when:** a controlled failure produces a reviewable Git diff without directly changing main or production.

## Phase 6: CI/CD and Staging Deployment

- Trigger the pipeline for an approved branch.
- Run backend and frontend tests.
- Run integration and end-to-end tests.
- Build versioned images.
- Deploy to staging.
- Run smoke and health tests.
- Display live pipeline status.
- Block production promotion on test or review failure.

**Done when:** an approved fix can move automatically from Git through CI to a verified staging environment.

## Phase 7: Production Promotion and Verification

- Add manual production approval.
- Promote an already tested image.
- Verify version and health after deployment.
- Re-check the triggering incident.
- Mark the incident resolved only when verification succeeds.
- Add rollback to the previous healthy image.
- Store the full timeline.

**Done when:** an approved fix can be deployed, verified, audited, and rolled back.

## Phase 8: Allow-Listed Self-Healing Demonstration

- Select one low-risk, deterministic demonstration scenario.
- Create explicit eligibility rules.
- Limit the number of fix attempts.
- Enable automatic staging deployment.
- Optionally enable controlled production promotion for the course demonstration.
- Verify that unknown failures stop and ask for human action.

**Done when:** one controlled incident can be detected, diagnosed, fixed, tested, deployed, and verified end to end without bypassing quality gates.

---

## 13. Weekend MVP Schedule

This schedule is intentionally smaller than the complete course project.

### Friday Evening: Preparation

- Create repository and project board.
- Write README and architecture outline.
- Add FastAPI and React skeletons.
- Add Docker Compose with PostgreSQL and Qdrant.
- Confirm that the Kanban application exposes logs and a health endpoint.

### Saturday Morning: Backend and Database

- Implement service registration.
- Implement log-ingestion endpoint.
- Store normalised logs.
- Implement simple deterministic error detection.
- Create incident records.
- Add backend unit tests.

### Saturday Afternoon: Frontend

- Create health overview.
- Create active-incident list.
- Create incident-detail page.
- Display related log events.
- Add live refresh through polling or an event stream.

### Saturday Evening: Local AI and RAG

- Connect to Ollama.
- Return validated structured analysis.
- Index selected Kanban documentation with Qdrant.
- Retrieve relevant documentation for an incident.
- Display diagnosis and sources in the UI.

### Sunday Morning: CI/CD and Deployment

- Add frontend and backend checks.
- Build container images.
- Deploy the Log Analyser to a production-like environment.
- Add a health check.
- Add application version information.

### Sunday Afternoon: Demonstration and Notifications

- Add one notification channel.
- Create a controlled failure-injection script.
- Trigger a Kanban failure.
- Confirm detection, incident creation, notification, RAG retrieval, and AI diagnosis.
- Record the result in the audit timeline.

### Sunday Evening: Documentation and Stretch Work

- Write setup and operational instructions.
- Document security limits.
- Add screenshots or a short demonstration recording.
- If time remains, generate a patch in a Git branch, but do not automatically deploy it yet.

### Weekend MVP Success Criteria

By the end of the weekend:

- The Log Analyser has a working frontend, backend, and PostgreSQL database.
- It is containerised and deployed through a pipeline.
- It monitors the Kanban backend.
- A controlled error creates an incident.
- The user receives one deduplicated notification.
- Local AI explains the incident.
- RAG retrieves relevant local documentation.
- The dashboard shows the complete incident timeline.

Automated code fixing and production self-healing remain later course-project phases.

---

## 14. Demonstration Scenarios

### Scenario 1: Database Connection Misconfiguration

1. Inject an invalid database host or port into a safe test/staging configuration.
2. Kanban backend fails its health check.
3. Log Analyser groups connection errors into one incident.
4. Notification is sent.
5. RAG retrieves the database runbook and deployment configuration.
6. AI explains the probable cause.
7. A controlled configuration fix is proposed.
8. CI verifies the change.
9. Staging is deployed and tested.
10. Production promotion requires approval.
11. Post-deployment checks confirm recovery.

### Scenario 2: Backend Exception

1. Enable a predefined faulty code path.
2. A request triggers an exception.
3. Logs contain the stack trace and application version.
4. RAG locates the relevant code and a similar previous incident.
5. A minimal code patch and regression test are proposed.
6. Code review and CI determine whether it can proceed.

### Scenario 3: Bad Release

1. Deploy an image that fails a health check in staging.
2. Pipeline blocks promotion.
3. Dashboard identifies the failed release.
4. No production modification occurs.
5. The event is stored in the audit history.

---

## 15. Test Strategy

### Unit Tests

- Log parsing and normalisation.
- Secret masking.
- Incident fingerprinting.
- Deduplication and cooldown logic.
- AI response validation.
- RAG filtering and metadata.
- Automatic-fix eligibility rules.
- Deployment state transitions.

### Integration Tests

- Log ingestion to incident creation.
- PostgreSQL persistence.
- Qdrant indexing and retrieval.
- Ollama adapter using deterministic test doubles in CI.
- Notification adapter.
- Git branch and diff creation.
- Pipeline callback handling.

### End-to-End Tests

- Open dashboard and view active incidents.
- Analyse an incident.
- Review retrieved evidence.
- Approve or reject a fix.
- View pipeline and deployment status.
- Confirm resolution timeline.

### Resilience Tests

- Ollama unavailable.
- Qdrant unavailable.
- PostgreSQL temporarily unavailable.
- Duplicate log storm.
- Invalid AI JSON.
- Notification failure.
- CI failure.
- Deployment health-check failure.
- Maximum fix attempts reached.

### Security Tests

- Unauthorised log submission.
- Secret masking.
- Path traversal in RAG indexing.
- Prompt injection inside indexed documents.
- Patch outside allowed directories.
- Command injection attempts.
- Oversized input.

---

## 16. Definition of Done

A feature is complete only when:

- Acceptance criteria are met.
- Backend and frontend tests pass.
- Failure cases are handled.
- Logs are structured and useful.
- No secrets are exposed.
- API changes are documented.
- Database changes have migrations.
- Containers build successfully.
- CI passes.
- Staging verification passes.
- User-facing behaviour is visible in the audit timeline.
- Documentation is updated.

---

## 17. Course Project Deliverables

- Source repository.
- Working frontend.
- Working backend API.
- Database schema and migrations.
- Local AI integration.
- Local-folder RAG pipeline.
- Automated tests.
- Docker-based local setup.
- CI/CD pipeline.
- Staging and production deployment configuration.
- Monitoring and notification integration.
- Architecture document.
- Threat model and safety constraints.
- Demonstration failure scenarios.
- Evaluation results.
- Final report.
- Demonstration video or live demonstration.

---

## 18. Evaluation Metrics

Record measurements for the final report:

- Incident detection precision on prepared test logs.
- Number of duplicate alerts suppressed.
- Time from injected failure to incident creation.
- Time from incident creation to notification.
- Whether the correct runbook/source file appears in the top retrieved results.
- Percentage of AI outputs that pass schema validation.
- Test pass/fail outcome for generated patches.
- Number of unsafe or out-of-scope changes blocked.
- Staging deployment success rate for prepared scenarios.
- Successful rollback and recovery verification.

Do not rely only on subjective claims that the AI response “looks correct”. Use prepared scenarios with expected results.

---

## 19. Suggested Milestones

- **M1:** Full-stack application skeleton deployed.
- **M2:** Logs create visible incidents and notifications.
- **M3:** Local AI explains incidents using structured output.
- **M4:** RAG searches local documentation and source code.
- **M5:** Proposed Git patch and code-review flow work.
- **M6:** CI deploys an approved fix to staging.
- **M7:** Production promotion, verification, and rollback work.
- **M8:** One safe self-healing scenario demonstrated end to end.

---

## 20. Recommended Starting Point

Start with one controlled database-connection failure and complete this path before adding more agents:

```text
Kanban failure
  -> structured log
  -> incident
  -> notification
  -> RAG retrieval
  -> AI diagnosis
  -> dashboard timeline
```

After that path is reliable, extend it to:

```text
AI diagnosis
  -> proposed Git patch
  -> code review
  -> tests
  -> staging deployment
  -> health verification
  -> approved production deployment
  -> rollback if unhealthy
```

This keeps the weekend MVP achievable while preserving the complete course-project vision.
