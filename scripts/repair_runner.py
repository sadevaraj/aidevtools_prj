#!/usr/bin/env python3
"""Gated Copilot repair boundary and strict candidate-patch policy."""

import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPOSITORY = "sadevaraj/aidevtools_prj"
AGENT = "Prj_Coordinator"
CLI_VERSION = "1.0.103"
OIDC_AUDIENCE = "sadevaraj/aidevtools_prj:repair-authorization"
CLAIM_PATH = "/api/alerts/repair/claim"
CLAIM_URL = f"https://simple-sudoku-backend.onrender.com{CLAIM_PATH}"
MAX_AUTH_RESPONSE_BYTES = 16_384
HTTP_TIMEOUT = 5
MAX_PATCH_BYTES = 20_000
MAX_PATCH_LINES = 160
ALLOWED_FILES = {
    "backend/app/main.py",
}
INCIDENT_ID = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
REPAIR_TEST = "test_deliberate_save_typo_reproduces_500_and_repaired_save_persists"
# Pin the complete, reviewed regression already shipped in test_api.py, not
# candidate-controlled marker strings. Updating this requires trusted review.
REPAIR_TEST_SHA256 = "787d9c664cb716bad7854cec66aa586001e2457d110c18ba12d698c3f07c275d"
DEMO_BRANCH = "main"
DEMO_BACKEND_TARGET = "https://simple-sudoku-backend.onrender.com"
DEMO_FRONTEND_TARGET = "https://simple-sudoku-frontend.onrender.com"
REVISION = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$", re.ASCII)


class RepairGateError(ValueError):
    """The dispatch or candidate does not fit the approved scope."""


def _regression_test_path(root: Path) -> Path:
    """Resolve the test in either the source checkout or backend test image."""
    for candidate in (
        root / "backend/tests/test_api.py",
        root / "tests/test_api.py",
    ):
        if candidate.is_file():
            return candidate
    raise RepairGateError("The approved save regression test is unavailable.")


def verify_agent_definitions(root: Path) -> None:
    """Require the actual repository agent identities and coordinator children."""
    expected = {
        "prj-coordinator.agent.md": (
            "Prj_Coordinator",
            ("Prj_Dev", "Prj_QA", "Prj_Reviewer"),
            "You coordinate delivery of Simple Sudoku.",
        ),
        "prj-dev.agent.md": (
            "Prj_Dev", (), "Implement one approved Simple Sudoku issue."
        ),
        "prj-qa.agent.md": (
            "Prj_QA", (), "Independently verify one issue after development."
        ),
        "prj-reviewer.agent.md": (
            "Prj_Reviewer", (), "Perform the final independent review for one issue."
        ),
    }
    for filename, (agent, children, required_text) in expected.items():
        path = root / ".github" / "agents" / filename
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as error:
            raise RepairGateError("Required agent definition is missing.") from error
        if not re.search(rf"(?m)^name:\s*{re.escape(agent)}\s*$", content):
            raise RepairGateError("Agent definition identity does not match.")
        if required_text not in content:
            raise RepairGateError("Agent role instructions do not match the repository definition.")
        if children:
            match = re.search(r"(?m)^agents:\s*\[([^\]]*)\]\s*$", content)
            configured = set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))) if match else set()
            if configured != set(children):
                raise RepairGateError("Coordinator agent allow-list is incomplete.")


def _unverified_access_one_attempt_approved(environment: dict[str, str]) -> bool:
    """Owner access-risk attestation, not provider entitlement or billing proof."""
    return all(environment.get(name) == "true" for name in (
        "REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED",
        "DEMO_CONTROL_REQUIRED",
        "DEMO_CONTROL_ENABLED",
    ))


def require_enabled(
    environment: dict[str, str],
    incident_id: str,
    expires_at: str,
    *,
    require_copilot_token: bool = True,
) -> None:
    """Require owner gates; unknown access needs the controlled one-attempt approval."""
    required = (
        "ALERT_REPAIR_ENABLED",
        "REPAIR_COPILOT_OWNER_ENABLED",
        "REPAIR_NO_OVERAGE_CONFIRMED",
        "REPAIR_PROVIDER_TRANSMISSION_APPROVED",
    )
    if any(environment.get(name) != "true" for name in required):
        raise RepairGateError("Owner Copilot entitlement, quota, privacy, and cost gates are not enabled.")
    if not all(environment.get(name) == "true" for name in (
        "REPAIR_FREE_ENTITLEMENT_CONFIRMED", "REPAIR_QUOTA_CONFIRMED",
    )) and not _unverified_access_one_attempt_approved(environment):
        raise RepairGateError("Verified access or explicit controlled one-attempt access-risk approval is required.")
    if environment.get("DEMO_CONTROL_REQUIRED") == "true" and environment.get("DEMO_CONTROL_ENABLED") != "true":
        raise RepairGateError("A durable owner demo authorization is required.")
    if environment.get("DEMO_CONTROL_REQUIRED") == "true" and (
        environment.get("PIPELINE_MODE") != "repair"
        or environment.get("GITHUB_WORKFLOW_REF")
        != f"{REPOSITORY}/.github/workflows/pipeline.yml@refs/heads/main"
    ):
        raise RepairGateError("Only the fixed pipeline repair dispatch is supported.")
    if environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise RepairGateError("Only the trusted workflow_dispatch event is supported.")
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise RepairGateError("Only the fixed Sudoku repository is supported.")
    if environment.get("GITHUB_REF") != "refs/heads/main":
        raise RepairGateError("Only the trusted main ref is supported.")
    if not INCIDENT_ID.fullmatch(incident_id):
        raise RepairGateError("Incident identifier is invalid.")
    expiry = _utc_datetime(expires_at)
    now = datetime.now(timezone.utc)
    if (
        expiry <= now
        or expiry > now + timedelta(minutes=31)
    ):
        raise RepairGateError("Incident has expired or exceeds the approved TTL.")
    if require_copilot_token and not environment.get("GITHUB_TOKEN"):
        raise RepairGateError("The workflow Copilot request token is unavailable.")


def _workflow_identity(environment: dict[str, str]) -> tuple[str, str]:
    values = (environment.get("GITHUB_RUN_ID", ""), environment.get("GITHUB_RUN_ATTEMPT", ""))
    if any(not re.fullmatch(r"[1-9][0-9]{0,18}", value, re.ASCII) for value in values):
        raise RepairGateError("Workflow run identity is invalid.")
    if int(values[0]) > 9_223_372_036_854_775_807 or int(values[1]) > 2_147_483_647:
        raise RepairGateError("Workflow run identity is invalid.")
    return values


def require_authorized_workflow(
    environment: dict[str, str], incident_id: str, expires_at: str
) -> None:
    """Reject inherited successful-job outputs on failed/specific-job reruns."""
    run_id, attempt = _workflow_identity(environment)
    if (
        environment.get("ALERT_REPAIR_AUTHORIZED") != "true"
        or environment.get("ALERT_REPAIR_AUTH_RUN_ID") != run_id
        or environment.get("ALERT_REPAIR_AUTH_RUN_ATTEMPT") != attempt
        or environment.get("ALERT_REPAIR_AUTH_INCIDENT_ID") != incident_id
        or environment.get("ALERT_REPAIR_AUTH_EXPIRES_AT") != expires_at
    ):
        raise RepairGateError("Receiver incident authorization did not succeed.")


def validate_demo_context(context: dict[str, str]) -> None:
    """Validate server-issued T/F, branch, image pair, rollback, and targets."""
    digest_keys = (
        "backend_digest",
        "frontend_digest",
        "rollback_backend_digest",
        "rollback_frontend_digest",
    )
    if (
        context.get("branch") != DEMO_BRANCH
        or not REVISION.fullmatch(context.get("trusted_revision", ""))
        or not REVISION.fullmatch(context.get("fault_revision", ""))
        or not REVISION.fullmatch(context.get("expected_repaired_tree", ""))
        or context.get("trusted_revision") == context.get("fault_revision")
        or any(not IMAGE_DIGEST.fullmatch(context.get(key, "")) for key in digest_keys)
        or context.get("backend_digest") == context.get("rollback_backend_digest")
        or context.get("frontend_digest") == context.get("rollback_frontend_digest")
        or context.get("backend_target") != DEMO_BACKEND_TARGET
        or context.get("frontend_target") != DEMO_FRONTEND_TARGET
    ):
        raise RepairGateError("Server-issued development demo authorization is invalid.")


DEMO_CONTEXT_KEYS = (
    "branch",
    "trusted_revision",
    "fault_revision",
    "expected_repaired_tree",
    "backend_digest",
    "frontend_digest",
    "rollback_backend_digest",
    "rollback_frontend_digest",
    "backend_target",
    "frontend_target",
)


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RepairGateError("Incident expiry is invalid.") from error
    if parsed.tzinfo is None:
        raise RepairGateError("Incident expiry must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _without_runner_credentials(environment: dict[str, str]) -> dict[str, str]:
    """Keep the one-time OIDC minting credential out of child processes."""
    child_environment = dict(environment)
    for name in (
        "GITHUB_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ALERT_REPAIR_PR_TOKEN",
    ):
        child_environment.pop(name, None)
    return child_environment


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_auth_json(response, deadline: float) -> dict:
    """Bound allocation and elapsed reads as well as each socket operation."""
    if response.status != 200 or response.headers.get_content_type() != "application/json":
        raise ValueError
    length = response.headers.get("Content-Length")
    if length is not None and (not length.isdecimal() or int(length) > MAX_AUTH_RESPONSE_BYTES):
        raise ValueError
    data = bytearray()
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError
        chunk = response.read1(min(4096, MAX_AUTH_RESPONSE_BYTES + 1 - len(data)))
        if time.monotonic() >= deadline:
            raise TimeoutError
        data.extend(chunk)
        if len(data) > MAX_AUTH_RESPONSE_BYTES:
            raise ValueError
        if not chunk:
            break
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError
    return payload


def authorize_incident(
    environment: dict[str, str],
    incident_id: str,
    expires_at: str,
    *,
    action: str,
    opener=None,
) -> dict[str, str]:
    """Ask the backend to verify/consume this workflow run's incident once."""
    auth_url = environment.get("ALERT_REPAIR_AUTH_URL", "")
    if (
        auth_url != CLAIM_URL
        or action not in {"claim", "verify"}
        or not INCIDENT_ID.fullmatch(incident_id)
        or "\n" in expires_at
        or "\r" in expires_at
    ):
        raise RepairGateError("The HTTPS receiver authorization endpoint is unavailable.")

    request_url = environment.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    request_token = environment.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    oidc_url = urlsplit(request_url)
    if oidc_url.scheme != "https" or not oidc_url.hostname or not request_token:
        raise RepairGateError("GitHub workflow identity is unavailable.")
    query = dict(parse_qsl(oidc_url.query, keep_blank_values=True))
    query["audience"] = OIDC_AUDIENCE
    token_url = urlunsplit(
        (oidc_url.scheme, oidc_url.netloc, oidc_url.path, urlencode(query), "")
    )
    run_id, attempt = _workflow_identity(environment)
    # Never follow a redirect with an identity token or use ambient HTTP proxies.
    open_url = opener or build_opener(ProxyHandler({}), _NoRedirect()).open
    try:
        token_request = Request(
            token_url,
            headers={"Authorization": f"Bearer {request_token}", "Accept": "application/json"},
        )
        deadline = time.monotonic() + HTTP_TIMEOUT
        with open_url(token_request, timeout=HTTP_TIMEOUT) as response:
            token_payload = _read_auth_json(response, deadline)
        oidc_token = token_payload["value"]
        if not isinstance(oidc_token, str) or not oidc_token or len(oidc_token) > 8192:
            raise ValueError
        claim_request = Request(
            auth_url,
            data=json.dumps(
                {
                    "incident_id": incident_id,
                    "expires_at": expires_at,
                    "action": action,
                },
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {oidc_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        deadline = time.monotonic() + HTTP_TIMEOUT
        with open_url(claim_request, timeout=HTTP_TIMEOUT) as response:
            authorization = _read_auth_json(response, deadline)
        if authorization.get("authorized") is not True:
            raise ValueError
        trusted_expiry = authorization["expires_at"]
        if _utc_datetime(trusted_expiry) != _utc_datetime(expires_at):
            raise ValueError
        if (
            authorization.get("run_id") != run_id
            or authorization.get("run_attempt") != attempt
            or authorization.get("incident_id") != incident_id
        ):
            raise ValueError
        demo_context = {
            key: authorization.get(key, "")
            for key in DEMO_CONTEXT_KEYS
        }
        if environment.get("DEMO_CONTROL_ENABLED") == "true":
            validate_demo_context(demo_context)
        elif any(demo_context.values()):
            validate_demo_context(demo_context)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        raise RepairGateError("The receiver rejected workflow incident authorization.") from None
    result = {
        "run_id": run_id,
        "run_attempt": attempt,
        "incident_id": incident_id,
        "expires_at": trusted_expiry,
    }
    if any(demo_context.values()):
        result.update(demo_context)
    return result


def copilot_command(prompt: str) -> list[str]:
    """Select the configured coordinator; do not allow unbounded shell tools."""
    return [
        "copilot",
        "--agent",
        AGENT,
        "--prompt",
        prompt,
        "--silent",
        "--allow-tool=write",
        "--allow-tool=shell(git:*)",
        "--deny-tool=shell(git push)",
    ]


def isolated_copilot_command(
    trusted_root: Path, workspace: Path, arguments: list[str], *, readonly: bool = False
) -> list[str]:
    """No host home, runner sockets, Actions OIDC, DB or publication credentials.

    The sole forwarded credential is the short-lived read/Copilot job token.
    Trusted agent instructions are overmounted read-only, even for DEV.
    """
    mounts = [
        "--mount", f"type=bind,src={workspace.resolve()},dst=/workspace"
        + (",readonly" if readonly else ""),
        "--mount", f"type=bind,src={(trusted_root / '.github').resolve()},dst=/workspace/.github,readonly",
    ]
    for path in ("AGENTS.md", "README.md", "docs"):
        mounts.extend([
            "--mount",
            f"type=bind,src={(trusted_root / path).resolve()},dst=/workspace/{path},readonly",
        ])
    return [
        "docker", "run", "--rm", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=128", "--memory=1g", "--cpus=2",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
        "--env", "GITHUB_TOKEN", "--env", "HOME=/tmp/home",
        *mounts, "sudoku-repair-runtime:trusted", *arguments,
    ]


def validate_patch(patch: bytes, existing_test_source: str = "") -> None:
    """Permit only the typo fix, using the existing immutable trusted regression.

    Candidate-authored tests are never accepted or executed. If the reviewed
    regression is absent or changed, this repair class is unsupported.
    """
    if not patch or len(patch) > MAX_PATCH_BYTES or b"\0" in patch:
        raise RepairGateError("Candidate patch is empty, oversized, or binary.")
    try:
        text = patch.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RepairGateError("Candidate patch is not UTF-8.") from error
    if len(text.splitlines()) > MAX_PATCH_LINES or "GIT binary patch" in text:
        raise RepairGateError("Candidate patch exceeds the bounded text limit.")
    paths = []
    current = None
    main_removed, main_added = [], []
    for line in text.splitlines():
        if line.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/([^ ]+) b/([^ ]+)", line)
            if not match or match.group(1) != match.group(2):
                raise RepairGateError("Renames and malformed patch paths are forbidden.")
            current = match.group(1)
            paths.append(current)
            if current not in ALLOWED_FILES:
                raise RepairGateError("Candidate patch changes a forbidden file.")
        elif line.startswith("--- "):
            if current is None or line[4:] != f"a/{current}":
                raise RepairGateError("Patch source path does not match the allow-list.")
        elif line.startswith("+++ "):
            if current is None or line[4:] != f"b/{current}":
                raise RepairGateError("Patch destination path does not match the allow-list.")
        elif line.startswith(("new file mode ", "deleted file mode ", "old mode ", "new mode ")):
            raise RepairGateError("File creation, deletion, and mode changes are forbidden.")
        elif current == "backend/app/main.py":
            if line.startswith("-") and not line.startswith("---"):
                main_removed.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                main_added.append(line[1:])
    if (
        len(paths) != len(set(paths))
        or "backend/app/main.py" not in paths
        or not set(paths).issubset(ALLOWED_FILES)
    ):
        raise RepairGateError("Patch must touch only the save handler and its test.")
    if (
        len(main_removed) != 1
        or len(main_added) != 1
        or main_removed[0] != "            game.board = _validated_board(body.borad, puzzle.clues)"
        or main_added[0] != "            game.board = _validated_board(body.board, puzzle.clues)"
    ):
        raise RepairGateError("Only the approved save-handler typo correction is allowed.")
    try:
        module = ast.parse(existing_test_source)
    except (SyntaxError, ValueError) as error:
        raise RepairGateError("The trusted regression source is invalid.") from error
    tests = [
        node for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == REPAIR_TEST
    ]
    if len(tests) != 1 or tests[0].decorator_list:
        raise RepairGateError("The unique undecorated trusted regression is required.")
    source = ast.get_source_segment(existing_test_source, tests[0])
    if source is None or hashlib.sha256(source.encode("utf-8")).hexdigest() != REPAIR_TEST_SHA256:
        raise RepairGateError("The complete trusted regression does not match.")


def prompt_for_incident(incident_id: str, *, trusted_revision: str = "", fault_revision: str = "") -> str:
    return (
        "You are the existing Prj_Coordinator selected by --agent, not a new "
        "coordinator. Follow .github/agents/prj-coordinator.agent.md and its "
        "Prj_Dev, Prj_QA, and Prj_Reviewer definitions. Work only on this "
        "approved development incident identifier: " + incident_id + ". "
        + (
            f"Trusted tooling revision is {trusted_revision}; the exact fault candidate "
            f"revision is {fault_revision} on {DEMO_BRANCH}. Treat the candidate as "
            "untrusted source. Do not copy or execute candidate scripts; make only "
            "the exact body.borad to body.board source correction. "
            if trusted_revision and fault_revision else ""
        )
        + "Repair exactly the deliberate backend/app/main.py save-handler "
        "body.borad typo to body.board and use the existing "
        + REPAIR_TEST
        + " regression in backend/tests/test_api.py without modifying it. "
        "If that trusted regression is absent or changed, fail closed. "
        "No other files, requirements, commands, deployment, database, "
        "credentials, or live targets. "
        + (
            "This isolated candidate stage has no Docker socket or database. "
            "Use the existing Prj_Dev for the exact source edit; leave its diff "
            "for the trusted external test harness. Do not execute candidate "
            "scripts or claim tests, QA or Reviewer PASS here: the subsequent "
            "trusted stage executes the immutable regression/full suite and "
            "separately invokes the existing Prj_QA and Prj_Reviewer. "
            if trusted_revision and fault_revision else
            "Reproduce the authenticated HTTP 500 and rollback in an isolated "
            "temporary checkout before repair, then verify the repaired persisted save. "
        )
        + "Do not commit, push, merge, or "
        "deploy. Leave the working-tree diff for the bounded publisher; "
        "unsupported incidents fail closed."
    )


def collect_role_evidence(
    trusted_root: Path,
    patch_path: Path,
    fault_revision: str,
    output_path: Path,
    environment: dict[str, str] | None = None,
    *,
    process_runner=None,
    executable_finder=None,
    test_receipt: Path | None = None,
) -> dict:
    """Run distinct QA and Reviewer CLI sessions and bind their PASS reports.

    The reviewer agents receive the exact patch and completed test result, not a
    candidate-controlled script or publication credential. Their own JSON must
    affirm a clean result for this exact revision and patch hash.
    """
    env = dict(os.environ if environment is None else environment)
    if not REVISION.fullmatch(fault_revision):
        raise RepairGateError("Fault candidate revision is invalid.")
    patch = patch_path.read_bytes()
    validate_patch(
        patch, _regression_test_path(trusted_root).read_text(encoding="utf-8")
    )
    patch_hash = hashlib.sha256(patch).hexdigest()
    verify_agent_definitions(trusted_root)
    runner = process_runner or subprocess.run
    find_executable = executable_finder or shutil.which
    copilot = find_executable("copilot", path=env.get("PATH"))
    demo = env.get("DEMO_CONTROL_ENABLED") == "true"
    receipt = None
    if demo:
        if test_receipt is None:
            raise RepairGateError("Trusted same-candidate test receipt is required.")
        receipt = validate_test_receipt(test_receipt, patch_hash, fault_revision, env)
    if (not copilot and not demo) or not env.get("GITHUB_TOKEN"):
        raise RepairGateError("The isolated Copilot review runtime is unavailable.")
    version = runner(
        isolated_copilot_command(trusted_root, trusted_root, ["--version"], readonly=True)
        if demo else [copilot, "--version"],
        cwd=trusted_root, env=_without_runner_credentials(env),
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()
    if version != f"GitHub Copilot CLI {CLI_VERSION}.":
        raise RepairGateError("The Copilot CLI version is not the pinned version.")

    diff_text = patch.decode("utf-8")
    reports = []
    for role, task in (
        ("Prj_QA", "Independently verify the exact repair and regression against acceptance criteria."),
        ("Prj_Reviewer", "Independently review the exact repair and QA evidence for correctness."),
    ):
        session_id = secrets.token_urlsafe(18)
        prompt = (
            f"Act only as the existing {role} custom agent. This is a fresh, independent "
            "review session. Review this exact patch after the configured full local "
            "test suite passed. Do not edit files or invoke shell commands. "
            f"Candidate fault revision: {fault_revision}. Patch SHA-256: {patch_hash}. "
            f"Task: {task} Return ONLY one JSON object with keys verdict (PASS or "
            "CHANGES_REQUESTED), fault_revision, patch_sha256, findings (array of "
            "concrete blocking findings). A PASS requires no blocking findings. "
            "Do not claim remote deployment, live alert, or rollback evidence. "
            + ("Trusted executed test receipt:\n" + json.dumps(receipt) + "\n" if receipt else "")
            +
            "Patch follows:\n" + diff_text
        )
        child_environment = _without_runner_credentials(env)
        child_environment["GITHUB_TOKEN"] = env["GITHUB_TOKEN"]
        arguments = ["--agent", role, "--prompt", prompt, "--silent",
                     "--deny-tool=write", "--deny-tool=shell", "--deny-tool=agent"]
        response = runner(
            isolated_copilot_command(trusted_root, trusted_root, arguments, readonly=True)
            if demo else ["copilot", *arguments],
            cwd=trusted_root,
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=900,
            check=True,
        )
        try:
            answer = json.loads(response.stdout)
        except (TypeError, ValueError) as error:
            raise RepairGateError(f"{role} did not return valid review evidence.") from error
        report = {
            "role": role,
            "verdict": answer.get("verdict") if isinstance(answer, dict) else None,
            "fault_revision": answer.get("fault_revision") if isinstance(answer, dict) else None,
            "patch_sha256": answer.get("patch_sha256") if isinstance(answer, dict) else None,
            "independent": True,
            "session_id": session_id,
            "findings": answer.get("findings") if isinstance(answer, dict) else None,
        }
        reports.append(report)
    validate_demo_evidence(reports[0], reports[1], fault_revision, patch_hash)
    evidence = {"patch_sha256": patch_hash, "fault_revision": fault_revision, "roles": reports}
    if receipt is not None:
        evidence["tests"] = receipt
    output_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def validate_demo_evidence(qa: object, reviewer: object, fault_revision: str, patch_sha256: str) -> None:
    """Validate distinct independent role evidence before exposing PR credentials."""
    expected_roles = ("Prj_QA", "Prj_Reviewer")
    for report, role in zip((qa, reviewer), expected_roles, strict=True):
        if (
            not isinstance(report, dict)
            or report.get("role") != role
            or report.get("verdict") != "PASS"
            or report.get("fault_revision") != fault_revision
            or report.get("patch_sha256") != patch_sha256
            or report.get("independent") is not True
            or not isinstance(report.get("session_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", report["session_id"])
            or report.get("findings") != []
        ):
            raise RepairGateError(f"Current {role} evidence is missing or does not bind to the patch.")
    if qa["session_id"] == reviewer["session_id"]:
        raise RepairGateError("QA and Reviewer evidence must come from distinct agent sessions.")


def verify_evidence_file(
    patch_path: Path, evidence_path: Path, fault_revision: str
) -> None:
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        patch_hash = hashlib.sha256(patch_path.read_bytes()).hexdigest()
        if (
            not isinstance(evidence, dict)
            or evidence.get("fault_revision") != fault_revision
            or evidence.get("patch_sha256") != patch_hash
            or not isinstance(evidence.get("roles"), list)
            or len(evidence["roles"]) != 2
        ):
            raise ValueError
        validate_demo_evidence(
            evidence["roles"][0], evidence["roles"][1], fault_revision, patch_hash
        )
        if os.environ.get("DEMO_CONTROL_ENABLED") == "true":
            validate_test_receipt_data(evidence.get("tests"), patch_hash, fault_revision, dict(os.environ))
    except (OSError, ValueError, TypeError, AttributeError):
        raise RepairGateError("Candidate QA and Reviewer evidence is invalid or stale.") from None


def validate_test_receipt_data(receipt, patch_hash: str, fault_revision: str, env: dict) -> dict:
    if not isinstance(receipt, dict) or any(
        receipt.get(key) != value
        for key, value in {
            "command": "sh scripts/test.sh", "returncode": 0,
            "patch_sha256": patch_hash, "fault_revision": fault_revision,
            "trusted_revision": env.get("ALERT_REPAIR_AUTH_TRUSTED_REVISION"),
            "repaired_tree": env.get("ALERT_REPAIR_AUTH_EXPECTED_REPAIRED_TREE"),
            "run_id": env.get("GITHUB_RUN_ID"),
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        }.items()
    ) or receipt.get("unverified_access_one_attempt_approved", False) is not _unverified_access_one_attempt_approved(env):
        raise RepairGateError("Trusted same-candidate test receipt is missing or stale.")
    return receipt


def validate_test_receipt(path: Path, patch_hash: str, fault_revision: str, env: dict) -> dict:
    try:
        return validate_test_receipt_data(json.loads(path.read_text()), patch_hash, fault_revision, env)
    except (OSError, ValueError, TypeError):
        raise RepairGateError("Trusted same-candidate test receipt is invalid.") from None


def test_repaired_candidate(trusted: Path, candidate: Path, patch: Path, output: Path) -> None:
    """Run only T's harness after proving the repaired candidate tree equals T."""
    from demo_control import expected_repaired_tree

    env = dict(os.environ)
    context = {key: env.get("ALERT_REPAIR_AUTH_" + key.upper(), "") for key in DEMO_CONTEXT_KEYS}
    validate_demo_context(context)
    validate_patch(patch.read_bytes(), _regression_test_path(trusted).read_text())
    expected = expected_repaired_tree(trusted, context["trusted_revision"], context["fault_revision"])
    def git(root, *args):
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True,
            text=True, timeout=15, env=_without_runner_credentials(env),
        ).stdout.strip()
    if (
        git(trusted, "rev-parse", "HEAD") != context["trusted_revision"]
        or git(candidate, "rev-parse", "HEAD") != context["fault_revision"]
        or git(candidate, "write-tree") != expected
        or context["expected_repaired_tree"] != expected
        or git(trusted, "status", "--porcelain")
        or git(candidate, "diff", "--name-only")
    ):
        raise RepairGateError("Repaired candidate or trusted test harness does not match the authorized tree.")
    subprocess.run(
        ["sh", "scripts/test.sh"], cwd=trusted, env=_without_runner_credentials(env),
        check=True, timeout=1500,
    )
    receipt = {
        "command": "sh scripts/test.sh", "returncode": 0,
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "fault_revision": context["fault_revision"],
        "trusted_revision": context["trusted_revision"], "repaired_tree": expected,
        "run_id": env.get("GITHUB_RUN_ID"), "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "unverified_access_one_attempt_approved": _unverified_access_one_attempt_approved(env),
    }
    output.write_text(json.dumps(receipt) + "\n")


def apply_candidate_patch(
    root: Path, patch_path: Path, *, trusted_root: Path | None = None
) -> None:
    patch = patch_path.read_bytes()
    trusted_root = trusted_root or root
    existing_test = _regression_test_path(trusted_root).read_text(encoding="utf-8")
    validate_patch(patch, existing_test)
    child_environment = _without_runner_credentials(dict(os.environ))
    subprocess.run(
        ["git", "apply", "--check", "--index", str(patch_path)],
        cwd=root,
        env=child_environment,
        check=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "apply", "--index", str(patch_path)],
        cwd=root,
        env=child_environment,
        check=True,
        timeout=10,
    )


def publish_pr(
    root: Path, incident_id: str, expires_at: str, patch_path: Path,
    *, trusted_root: Path | None = None,
    evidence_path: Path | None = None,
) -> None:
    """Publish a validated, tested patch without executing candidate code."""
    require_enabled(dict(os.environ), incident_id, expires_at)
    require_authorized_workflow(dict(os.environ), incident_id, expires_at)
    token = os.environ.get("ALERT_REPAIR_PR_TOKEN")
    if not token:
        raise RepairGateError("Owner-managed PR publication credential is unavailable.")
    if os.environ.get("DEMO_CONTROL_ENABLED") == "true":
        context = {
            key: os.environ.get("ALERT_REPAIR_AUTH_" + key.upper(), "")
            for key in DEMO_CONTEXT_KEYS
        }
        validate_demo_context(context)
        if os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise RepairGateError("Demo repair publication must originate from trusted main.")
        if (
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, timeout=10,
            ).stdout.strip() != context["fault_revision"]
            or subprocess.run(
                ["git", "-C", str(root), "branch", "--show-current"],
                check=True, capture_output=True, text=True, timeout=10,
            ).stdout.strip() != DEMO_BRANCH
        ):
            raise RepairGateError("Fault branch moved after its durable authorization.")
        if os.environ.get("DEMO_CONTROL_ENABLED") == "true":
            from demo_control import expected_repaired_tree

            if expected_repaired_tree(
                trusted_root or root,
                context["trusted_revision"],
                context["fault_revision"],
            ) != context["expected_repaired_tree"]:
                raise RepairGateError("Expected repaired tree does not match the authorized T/F pair.")
        if evidence_path is None:
            raise RepairGateError("Current candidate QA and Reviewer evidence is required.")
        verify_evidence_file(
            patch_path,
            evidence_path,
            os.environ.get("ALERT_REPAIR_AUTH_FAULT_REVISION", ""),
        )
        branch = f"repair/save-recovery-{incident_id[:12]}"
    else:
        branch = f"repair/alert-{incident_id[:12]}"
    apply_candidate_patch(root, patch_path, trusted_root=trusted_root)
    child_environment = _without_runner_credentials(dict(os.environ))
    if os.environ.get("DEMO_CONTROL_ENABLED") == "true":
        tree = subprocess.run(
            ["git", "write-tree"], cwd=root, env=child_environment,
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if tree != context["expected_repaired_tree"]:
            raise RepairGateError("Publication tree differs from the authorized tested repair.")
    subprocess.run(
        ["git", "config", "user.name", "sudoku-alert-repair[bot]"],
        cwd=root, env=child_environment, check=True, timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.email", "sudoku-alert-repair[bot]@users.noreply.github.com"],
        cwd=root, env=child_environment, check=True, timeout=10,
    )
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=root, env=child_environment, check=True, timeout=10,
    )
    subprocess.run(
        ["git", "add", "--", *sorted(ALLOWED_FILES)],
        cwd=root, env=child_environment, check=True, timeout=10,
    )
    subprocess.run(
        ["git", "commit", "-m", "Repair bounded Sudoku save alert"],
        cwd=root, env=child_environment, check=True, timeout=30,
    )
    # Git uses the checkout's owner-managed token credential. `gh` uses the
    # separate token so its PR event triggers the ordinary PR pipeline.
    def verify_remote_tip():
        if os.environ.get("DEMO_CONTROL_ENABLED") != "true":
            return
        tip = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{DEMO_BRANCH}"],
            cwd=root, env=child_environment, check=True, capture_output=True,
            text=True, timeout=20,
        ).stdout.strip()
        if tip != f"{context['fault_revision']}\trefs/heads/{DEMO_BRANCH}":
            raise RepairGateError("Remote demo branch moved; publication is blocked.")
    verify_remote_tip()
    subprocess.run(
        ["git", "push", "--set-upstream", "origin", branch],
        cwd=root, env=child_environment, check=True, timeout=60,
    )
    verify_remote_tip()
    subprocess.run(
        [
            "gh", "pr", "create",
            "--repo", REPOSITORY,
            "--base", DEMO_BRANCH if os.environ.get("DEMO_CONTROL_ENABLED") == "true" else "main",
            "--head", branch,
            "--title", "Repair bounded Sudoku save alert",
            "--body",
            (
                "This PR contains only the approved save-handler typo correction "
                "using the unchanged trusted authenticated HTTP failure/rollback/persistence test. "
                "Generated from a bounded alert workflow with same-patch independent role evidence. "
                "Human review and manual non-squash merge onto the authorized demo branch "
                "are required; owner-enabled development deployment is gated on full CI."
            ),
        ],
        cwd=root,
        env={**child_environment, "GH_TOKEN": token},
        check=True,
        timeout=60,
    )


def run_candidate(
    root: Path,
    incident_id: str,
    expires_at: str,
    output: Path,
    environment=None,
    process_runner=None,
    executable_finder=None,
    candidate_root: Path | None = None,
) -> None:
    env = dict(os.environ if environment is None else environment)
    require_enabled(env, incident_id, expires_at)
    require_authorized_workflow(env, incident_id, expires_at)
    candidate_root = candidate_root or root
    trusted_revision = ""
    fault_revision = ""
    if env.get("DEMO_CONTROL_ENABLED") == "true":
        from demo_control import validate_revisions

        context = {
            key: env.get("ALERT_REPAIR_AUTH_" + key.upper(), "")
            for key in DEMO_CONTEXT_KEYS
        }
        validate_demo_context(context)
        trusted_revision = context["trusted_revision"]
        fault_revision = context["fault_revision"]
        if (
            env.get("GITHUB_REF") != "refs/heads/main"
            or subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, timeout=10,
            ).stdout.strip() != trusted_revision
            or subprocess.run(
                ["git", "-C", str(candidate_root), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True, timeout=10,
            ).stdout.strip() != fault_revision
        ):
            raise RepairGateError("Trusted or fault checkout moved after authorization.")
        validate_revisions(root, trusted_revision, fault_revision)
        if subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify",
             f"refs/remotes/origin/{DEMO_BRANCH}"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip() != fault_revision:
            raise RepairGateError("Authorized fault branch tip moved.")
        if subprocess.run(
            ["git", "-C", str(root), "rev-parse", f"{trusted_revision}^{{tree}}"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip() != context["expected_repaired_tree"]:
            raise RepairGateError("Expected repaired tree does not match trusted revision.")
    verify_agent_definitions(root)
    runner = process_runner or subprocess.run
    find_executable = executable_finder or shutil.which
    copilot = find_executable("copilot", path=env.get("PATH"))
    demo = env.get("DEMO_CONTROL_ENABLED") == "true"
    if not copilot and not demo:
        raise RepairGateError("The pinned Copilot CLI is unavailable.")
    child_environment = _without_runner_credentials(env)
    version = runner(
        isolated_copilot_command(root, candidate_root, ["--version"])
        if demo else [copilot, "--version"],
        cwd=root, env=child_environment,
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()
    if version != f"GitHub Copilot CLI {CLI_VERSION}.":
        raise RepairGateError("The Copilot CLI version is not the pinned version.")
    # Give the short-lived token only to the Copilot process, never to tests or
    # candidate application code in the later verification job.
    prompt = prompt_for_incident(
        incident_id,
        trusted_revision=trusted_revision,
        fault_revision=fault_revision,
    )
    cli_env = dict(child_environment)
    cli_env["GITHUB_TOKEN"] = env["GITHUB_TOKEN"]
    runner(
        isolated_copilot_command(root, candidate_root, copilot_command(prompt)[1:])
        if demo else copilot_command(prompt),
        cwd=candidate_root, env=cli_env, timeout=900, check=True
    )
    status_result = runner(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=candidate_root,
        env=child_environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    for line in status_result.stdout.splitlines():
        path = line[3:] if len(line) >= 4 else ""
        if line[:2] != " M" or path not in ALLOWED_FILES:
            raise RepairGateError("Candidate worktree changed a forbidden path or staged files.")
    patch = runner(
        ["git", "diff", "--binary", "--", *sorted(ALLOWED_FILES)],
        cwd=candidate_root, env=child_environment,
        capture_output=True, timeout=10, check=True,
    ).stdout
    existing_test = _regression_test_path(root).read_text(encoding="utf-8")
    validate_patch(patch, existing_test)
    output.write_bytes(patch)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--incident-id", required=True)
    run_parser.add_argument("--expires-at", required=True)
    run_parser.add_argument("--patch", type=Path, required=True)
    run_parser.add_argument("--candidate-root", type=Path)
    validate_parser = subparsers.add_parser("validate-patch")
    validate_parser.add_argument("patch", type=Path)
    apply_parser = subparsers.add_parser("apply-patch")
    apply_parser.add_argument("patch", type=Path)
    apply_parser.add_argument("--candidate-root", type=Path)
    authorize_parser = subparsers.add_parser("authorize")
    authorize_parser.add_argument("--incident-id", required=True)
    authorize_parser.add_argument("--expires-at", required=True)
    verify_parser = subparsers.add_parser("verify-authorization")
    verify_parser.add_argument("--incident-id", required=True)
    verify_parser.add_argument("--expires-at", required=True)
    publish_parser = subparsers.add_parser("publish-pr")
    publish_parser.add_argument("--incident-id", required=True)
    publish_parser.add_argument("--expires-at", required=True)
    publish_parser.add_argument("--patch", type=Path, required=True)
    publish_parser.add_argument("--candidate-root", type=Path)
    publish_parser.add_argument("--evidence", type=Path)
    review_parser = subparsers.add_parser("collect-reviews")
    review_parser.add_argument("--patch", type=Path, required=True)
    review_parser.add_argument("--fault-revision", required=True)
    review_parser.add_argument("--output", type=Path, required=True)
    review_parser.add_argument("--test-receipt", type=Path)
    test_parser = subparsers.add_parser("test-candidate")
    test_parser.add_argument("--candidate-root", type=Path, required=True)
    test_parser.add_argument("--patch", type=Path, required=True)
    test_parser.add_argument("--output", type=Path, required=True)
    evidence_parser = subparsers.add_parser("verify-evidence")
    evidence_parser.add_argument("--patch", type=Path, required=True)
    evidence_parser.add_argument("--evidence", type=Path, required=True)
    evidence_parser.add_argument("--fault-revision", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            run_candidate(
                Path.cwd(), args.incident_id, args.expires_at, args.patch,
                candidate_root=args.candidate_root,
            )
        elif args.command == "collect-reviews":
            collect_role_evidence(
                Path.cwd(), args.patch, args.fault_revision, args.output,
                test_receipt=args.test_receipt,
            )
        elif args.command == "test-candidate":
            test_repaired_candidate(Path.cwd(), args.candidate_root, args.patch, args.output)
        elif args.command == "verify-evidence":
            verify_evidence_file(args.patch, args.evidence, args.fault_revision)
        elif args.command == "validate-patch":
            validate_patch(args.patch.read_bytes())
        elif args.command == "apply-patch":
            apply_candidate_patch(
                args.candidate_root or Path.cwd(),
                args.patch,
                trusted_root=Path.cwd(),
            )
        elif args.command in {"authorize", "verify-authorization"}:
            environment = dict(os.environ)
            require_enabled(
                environment,
                args.incident_id,
                args.expires_at,
                require_copilot_token=False,
            )
            if (
                environment.get("DEMO_CONTROL_REQUIRED") == "true"
                and environment.get("DEMO_CONTROL_ENABLED") != "true"
            ):
                raise RepairGateError("The owner-gated save-recovery demo is not enabled.")
            if args.command == "authorize":
                authorization = authorize_incident(
                    environment,
                    args.incident_id,
                    args.expires_at,
                    action="claim",
                )
                # Only this trusted, isolated step writes job outputs, after
                # the backend has consumed and echoed the signed run identity.
                with open(environment["GITHUB_OUTPUT"], "a", encoding="utf-8") as outputs:
                    outputs.write("".join(f"{key}={value}\n" for key, value in authorization.items()))
            else:
                require_authorized_workflow(environment, args.incident_id, args.expires_at)
                if environment.get("DEMO_CONTROL_ENABLED") == "true":
                    context = {
                        key: environment.get("ALERT_REPAIR_AUTH_" + key.upper(), "")
                        for key in DEMO_CONTEXT_KEYS
                    }
                    validate_demo_context(context)
                    current = authorize_incident(
                        environment, args.incident_id, args.expires_at, action="verify"
                    )
                    if any(current.get(key) != value for key, value in context.items()):
                        raise RepairGateError("Receiver binding changed after the workflow claim.")
        else:
            publish_pr(
                args.candidate_root or Path.cwd(), args.incident_id,
                args.expires_at, args.patch, trusted_root=Path.cwd(),
                evidence_path=args.evidence,
            )
    except (
        RepairGateError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Repair run blocked: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
