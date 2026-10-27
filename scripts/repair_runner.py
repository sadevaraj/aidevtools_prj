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
REPAIR_TEST_SHA256 = "9da5aa6a430bfbbf9849876fea02bdacd7bda29f2608b96d9b542875e1249426"


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


def require_enabled(
    environment: dict[str, str],
    incident_id: str,
    expires_at: str,
    *,
    require_copilot_token: bool = True,
) -> None:
    """Fail closed unless the owner explicitly enabled every free-only gate."""
    required = (
        "ALERT_REPAIR_ENABLED",
        "REPAIR_COPILOT_OWNER_ENABLED",
        "REPAIR_FREE_ENTITLEMENT_CONFIRMED",
        "REPAIR_QUOTA_CONFIRMED",
        "REPAIR_NO_OVERAGE_CONFIRMED",
        "REPAIR_PROVIDER_TRANSMISSION_APPROVED",
    )
    if any(environment.get(name) != "true" for name in required):
        raise RepairGateError("Owner Copilot entitlement, quota, privacy, and cost gates are not enabled.")
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
    return {
        "run_id": run_id,
        "run_attempt": attempt,
        "incident_id": incident_id,
        "expires_at": trusted_expiry,
    }


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
        or "body.borad" not in main_removed[0]
        or "body.board" not in main_added[0]
        or main_removed[0].replace("body.borad", "body.board") != main_added[0]
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


def prompt_for_incident(incident_id: str) -> str:
    return (
        "You are the existing Prj_Coordinator selected by --agent, not a new "
        "coordinator. Follow .github/agents/prj-coordinator.agent.md and its "
        "Prj_Dev, Prj_QA, and Prj_Reviewer definitions. Work only on this "
        "approved local test incident identifier: " + incident_id + ". "
        "Repair exactly the deliberate backend/app/main.py save-handler "
        "body.borad typo to body.board and use the existing "
        + REPAIR_TEST
        + " regression in backend/tests/test_api.py without modifying it. "
        "If that trusted regression is absent or changed, fail closed. "
        "No other files, requirements, "
        "commands, deployment, database, credentials, or live targets. "
        "Reproduce the authenticated HTTP 500 and rollback in an isolated "
        "temporary checkout before repair, then verify the repaired persisted "
        "save. Do not commit, push, merge, or deploy. QA and Reviewer review "
        "the same candidate. Leave the working-tree diff for the bounded "
        "publisher; unsupported incidents fail closed."
    )


def apply_candidate_patch(root: Path, patch_path: Path) -> None:
    patch = patch_path.read_bytes()
    existing_test = _regression_test_path(root).read_text(encoding="utf-8")
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
    root: Path, incident_id: str, expires_at: str, patch_path: Path
) -> None:
    """Publish a validated, tested patch without executing candidate code."""
    require_enabled(dict(os.environ), incident_id, expires_at)
    require_authorized_workflow(dict(os.environ), incident_id, expires_at)
    token = os.environ.get("ALERT_REPAIR_PR_TOKEN")
    if not token:
        raise RepairGateError("Owner-managed PR publication credential is unavailable.")
    branch = f"repair/alert-{incident_id[:12]}"
    apply_candidate_patch(root, patch_path)
    child_environment = _without_runner_credentials(dict(os.environ))
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
    subprocess.run(
        ["git", "push", "--set-upstream", "origin", branch],
        cwd=root, env=child_environment, check=True, timeout=60,
    )
    subprocess.run(
        [
            "gh", "pr", "create",
            "--repo", REPOSITORY,
            "--base", "main",
            "--head", branch,
            "--title", "Repair bounded Sudoku save alert",
            "--body",
            (
                "This PR contains only the approved save-handler typo correction "
                "and focused authenticated HTTP failure/rollback/persistence test. "
                "Generated from a bounded alert workflow. Human review, merge, "
                "and deployment remain required."
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
) -> None:
    env = dict(os.environ if environment is None else environment)
    require_enabled(env, incident_id, expires_at)
    require_authorized_workflow(env, incident_id, expires_at)
    verify_agent_definitions(root)
    runner = process_runner or subprocess.run
    find_executable = executable_finder or shutil.which
    copilot = find_executable("copilot", path=env.get("PATH"))
    if not copilot:
        raise RepairGateError("The pinned Copilot CLI is unavailable.")
    child_environment = _without_runner_credentials(env)
    version = runner(
        [copilot, "--version"], cwd=root, env=child_environment,
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()
    if version != f"GitHub Copilot CLI {CLI_VERSION}.":
        raise RepairGateError("The Copilot CLI version is not the pinned version.")
    # Give the short-lived token only to the Copilot process, never to tests or
    # candidate application code in the later verification job.
    prompt = prompt_for_incident(incident_id)
    cli_env = dict(child_environment)
    cli_env["GITHUB_TOKEN"] = env["GITHUB_TOKEN"]
    runner(
        copilot_command(prompt), cwd=root, env=cli_env, timeout=900, check=True
    )
    status_result = runner(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
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
        cwd=root, env=child_environment,
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
    validate_parser = subparsers.add_parser("validate-patch")
    validate_parser.add_argument("patch", type=Path)
    apply_parser = subparsers.add_parser("apply-patch")
    apply_parser.add_argument("patch", type=Path)
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
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            run_candidate(Path.cwd(), args.incident_id, args.expires_at, args.patch)
        elif args.command == "validate-patch":
            validate_patch(args.patch.read_bytes())
        elif args.command == "apply-patch":
            apply_candidate_patch(Path.cwd(), args.patch)
        elif args.command in {"authorize", "verify-authorization"}:
            environment = dict(os.environ)
            require_enabled(
                environment,
                args.incident_id,
                args.expires_at,
                require_copilot_token=False,
            )
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
        else:
            publish_pr(
                Path.cwd(), args.incident_id, args.expires_at, args.patch
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
