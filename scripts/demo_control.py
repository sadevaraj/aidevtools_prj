#!/usr/bin/env python3
"""Fail-closed controls for the one approved development save-recovery demo."""

import argparse
import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

BRANCH = "demo/save-recovery"
REPOSITORY = "sadevaraj/aidevtools_prj"
BACKEND_TARGET = "https://simple-sudoku-backend.onrender.com"
FRONTEND_TARGET = "https://simple-sudoku-frontend.onrender.com"
SOURCE_PATH = "backend/app/main.py"
CORRECT_LINE = "game.board = _validated_board(body.board, puzzle.clues)"
FAULT_LINE = "game.board = _validated_board(body.borad, puzzle.clues)"
SHA = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$", re.ASCII)
EVIDENCE_URL = re.compile(
    r"^https://github\.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-[0-9]+$",
    re.ASCII,
)


class DemoGateError(ValueError):
    """Only fixed safe diagnostics are emitted by this helper."""


def validate_window(value: str) -> None:
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if expiry.tzinfo is None or not now < expiry <= now + timedelta(hours=1):
            raise ValueError
    except (ValueError, TypeError):
        raise DemoGateError("Explicit unexpired development window of at most one hour is required.") from None


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DemoGateError("Git revision verification failed.") from error
    return result.stdout.strip()


def validate_revisions(root: Path, trusted_revision: str, fault_revision: str) -> None:
    """Accept only a single one-line save-handler fault on the demo branch."""
    if not SHA.fullmatch(trusted_revision) or not SHA.fullmatch(fault_revision):
        raise DemoGateError("Trusted and fault revisions must be full lowercase commit IDs.")
    if trusted_revision == fault_revision:
        raise DemoGateError("The trusted and fault revisions must differ.")
    if _git(root, "rev-parse", "--verify", f"{trusted_revision}^{{commit}}") != trusted_revision:
        raise DemoGateError("Trusted revision is unavailable.")
    if _git(root, "rev-parse", "--verify", f"{fault_revision}^{{commit}}") != fault_revision:
        raise DemoGateError("Fault revision is unavailable.")
    try:
        subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", trusted_revision, fault_revision],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DemoGateError("Fault revision is not a descendant of the trusted revision.") from error
    if _git(root, "rev-list", "--count", f"{trusted_revision}..{fault_revision}") != "1":
        raise DemoGateError("Fault revision must contain exactly one approved demo commit.")
    names = _git(root, "diff", "--name-status", trusted_revision, fault_revision).splitlines()
    if names != [f"M\t{SOURCE_PATH}"]:
        raise DemoGateError("Demo revision changes paths outside the approved save handler.")
    diff = _git(
        root, "diff", "--no-ext-diff", "--unified=0",
        trusted_revision, fault_revision, "--", SOURCE_PATH,
    )
    removed = [line[1:] for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    if (
        len(removed) != 1 or len(added) != 1
        or removed[0].lstrip() != CORRECT_LINE or added[0].lstrip() != FAULT_LINE
        or removed[0].replace("body.board", "body.borad") != added[0]
    ):
        raise DemoGateError("Demo commit is not the exact approved one-line save-handler fault.")
    trusted_source = _git(root, "show", f"{trusted_revision}:{SOURCE_PATH}")
    fault_source = _git(root, "show", f"{fault_revision}:{SOURCE_PATH}")
    if trusted_source.count(CORRECT_LINE) != 1 or fault_source.count(FAULT_LINE) != 1:
        raise DemoGateError("Save-handler source does not match the approved healthy/faulted pair.")
    try:
        functions = [
            node for node in ast.walk(ast.parse(trusted_source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "save_game"
        ]
        if len(functions) != 1 or CORRECT_LINE not in ast.get_source_segment(trusted_source, functions[0]):
            raise ValueError
    except (ValueError, SyntaxError, TypeError):
        raise DemoGateError("The approved line must belong to the save_game handler.") from None


def validate_owner_gates(environment: dict[str, str]) -> None:
    required = (
        "DEMO_FAULT_ENABLED",
        "DEMO_ROLLBACK_PAIR_VERIFIED",
        "DEMO_WINDOW_CONFIRMED",
        "DEMO_IMAGE_PROVENANCE_VERIFIED",
        "DEMO_TARGETS_CONFIRMED",
    )
    if any(environment.get(name) != "true" for name in required):
        raise DemoGateError("Owner prerequisites, development window, or rollback gates are missing.")
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise DemoGateError("Only the fixed Sudoku repository is supported.")
    if (
        environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or environment.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise DemoGateError("Fault publication must be owner-dispatched from trusted main.")
    evidence_url = environment.get("DEMO_ROLLBACK_EVIDENCE_URL", "")
    if not EVIDENCE_URL.fullmatch(evidence_url):
        raise DemoGateError("Current issue #13 rollback evidence is required.")
    validate_window(environment.get("DEMO_EXPIRES_AT", ""))


def validate_image_pair(
    *, backend_digest: str, frontend_digest: str,
    rollback_backend_digest: str, rollback_frontend_digest: str,
    backend_target: str, frontend_target: str,
) -> None:
    if not all(
        DIGEST.fullmatch(value)
        for value in (
            backend_digest, frontend_digest,
            rollback_backend_digest, rollback_frontend_digest,
        )
    ):
        raise DemoGateError("Current and rollback image references must be immutable digests.")
    if (
        backend_digest == rollback_backend_digest
        or frontend_digest == rollback_frontend_digest
        or backend_target != BACKEND_TARGET
        or frontend_target != FRONTEND_TARGET
    ):
        raise DemoGateError("Image pair or development target does not match the approved demo.")


def validate_role_evidence(
    qa: object, reviewer: object, *, fault_revision: str, patch_sha256: str,
) -> None:
    """Require two distinct, diff-bound role reports before PR publication."""
    if not SHA.fullmatch(fault_revision) or not re.fullmatch(r"[0-9a-f]{64}", patch_sha256):
        raise DemoGateError("Candidate evidence binding is invalid.")
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
            or not isinstance(report.get("findings"), list)
            or report["findings"]
        ):
            raise DemoGateError(f"Current {role} evidence is missing or does not bind to the patch.")
    if qa["session_id"] == reviewer["session_id"]:
        raise DemoGateError("QA and Reviewer evidence must come from distinct agent sessions.")


def expected_repaired_tree(root: Path, trusted_revision: str, fault_revision: str) -> str:
    """Compute only the one approved repaired tree; no source is executed."""
    validate_revisions(root, trusted_revision, fault_revision)
    return _git(root, "rev-parse", f"{trusted_revision}^{{tree}}")


def verify_merge(environment: dict[str, str], root: Path) -> None:
    """Gate the demo branch pipeline on the exact authorized healthy tree."""
    if (
        environment.get("GITHUB_REPOSITORY") != REPOSITORY
        or environment.get("GITHUB_REF") != f"refs/heads/{BRANCH}"
        or environment.get("GITHUB_EVENT_NAME") != "push"
        or environment.get("DEMO_RECOVERY_ENABLED") != "true"
    ):
        raise DemoGateError("Only the owner-enabled demo branch push is eligible for recovery delivery.")
    expected_tree = environment.get("DEMO_EXPECTED_REPAIRED_TREE", "")
    actual_tree = _git(root, "rev-parse", "HEAD^{tree}")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_tree) or actual_tree != expected_tree:
        raise DemoGateError("Demo branch tip is not the exact authorized repaired tree.")
    trusted = environment.get("DEMO_TRUSTED_REVISION", "")
    fault = environment.get("DEMO_FAULT_REVISION", "")
    validate_window(environment.get("DEMO_EXPIRES_AT", ""))
    if expected_repaired_tree(root, trusted, fault) != expected_tree:
        raise DemoGateError("Recovery tree does not match the authorized T/F pair.")
    parents = _git(root, "show", "-s", "--format=%P", "HEAD").split()
    if len(parents) != 2 or parents[0] != fault:
        raise DemoGateError("Recovery requires a manual non-squash merge directly onto F.")
    if _git(root, "rev-parse", f"{parents[1]}^{{tree}}") != expected_tree:
        raise DemoGateError("Merged repair candidate does not match the tested tree.")


def publish_image_pair(environment: dict[str, str]) -> dict[str, str]:
    """Push only prebuilt artifact images; this job never checks out candidate code."""
    fault_revision = environment.get("DEMO_FAULT_REVISION", "")
    if not SHA.fullmatch(fault_revision):
        raise DemoGateError("Fault image revision is invalid.")
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise DemoGateError("Only the fixed Sudoku repository is supported.")
    results: dict[str, str] = {}
    for role in ("backend", "frontend"):
        local = f"localhost/simple-sudoku-{role}:{fault_revision}"
        try:
            inspected = subprocess.run(
                ["docker", "image", "inspect", local, "--format", "{{json .Config.Labels}}"],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            labels = json.loads(inspected.stdout)
            if (
                not isinstance(labels, dict)
                or labels.get("org.opencontainers.image.source")
                != f"https://github.com/{REPOSITORY}"
                or labels.get("org.opencontainers.image.revision") != fault_revision
            ):
                raise DemoGateError("Built image provenance does not match the authorized fault revision.")
            image = f"ghcr.io/sadevaraj/simple-sudoku-{role}:{fault_revision}"
            subprocess.run(
                ["docker", "tag", local, image],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            pushed = subprocess.run(
                ["docker", "push", image],
                check=True,
                capture_output=True,
                text=True,
                timeout=1200,
            )
        except DemoGateError:
            raise
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise DemoGateError(f"{role} image publication failed; inspect the trusted workflow run.") from error
        digests = re.findall(r"(?m)(?:^| )digest:\s*(sha256:[0-9a-f]{64})(?:\s|$)", pushed.stdout)
        if len(digests) != 1:
            raise DemoGateError(f"{role} registry digest was not returned unambiguously.")
        results[role] = digests[0]
    return results


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def arm_demo(environment: dict[str, str], root: Path, *, opener=None) -> None:
    """Bind the workflow-built pair on the healthy server before fault deployment."""
    validate_owner_gates(environment)
    trusted = environment.get("TRUSTED_REVISION", "")
    fault = environment.get("FAULT_REVISION", "")
    tree = expected_repaired_tree(root, trusted, fault)
    if _git(root, "rev-parse", "refs/remotes/origin/demo/save-recovery") != fault:
        raise DemoGateError("Fault branch moved before server authorization.")
    validate_image_pair(
        backend_digest=environment.get("BACKEND_DIGEST", ""),
        frontend_digest=environment.get("FRONTEND_DIGEST", ""),
        rollback_backend_digest=environment.get("DEMO_ROLLBACK_BACKEND_DIGEST", ""),
        rollback_frontend_digest=environment.get("DEMO_ROLLBACK_FRONTEND_DIGEST", ""),
        backend_target=BACKEND_TARGET, frontend_target=FRONTEND_TARGET,
    )
    token = environment.get("DEMO_CONTROL_TOKEN", "")
    if not token:
        raise DemoGateError("Owner-managed demo control credential is unavailable.")
    payload = {
        "trusted_revision": trusted, "fault_revision": fault,
        "expected_repaired_tree": tree, "branch": BRANCH,
        "backend_digest": environment["BACKEND_DIGEST"],
        "frontend_digest": environment["FRONTEND_DIGEST"],
        "rollback_backend_digest": environment["DEMO_ROLLBACK_BACKEND_DIGEST"],
        "rollback_frontend_digest": environment["DEMO_ROLLBACK_FRONTEND_DIGEST"],
        "expires_at": environment["DEMO_EXPIRES_AT"],
        "rollback_evidence_url": environment["DEMO_ROLLBACK_EVIDENCE_URL"],
        "rollback_pair_verified": True, "development_window_confirmed": True,
        "image_provenance_verified": True,
    }
    request = Request(
        BACKEND_TARGET + "/api/alerts/demo/arm",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        open_url = opener or build_opener(ProxyHandler({}), NoRedirect()).open
        with open_url(request, timeout=5) as response:
            result = json.loads(response.read(4097))
            if response.status != 201 or result.get("armed") is not True or any(
                result.get(key) != payload[key]
                for key in ("trusted_revision", "fault_revision", "expected_repaired_tree", "branch")
            ):
                raise ValueError
    except Exception:
        raise DemoGateError("Server demo authorization failed; stop and inspect owner evidence.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("verify-candidate")
    candidate.add_argument("--trusted-revision", required=True)
    candidate.add_argument("--fault-revision", required=True)
    candidate.add_argument("--repo", type=Path, default=Path.cwd())
    merge = commands.add_parser("verify-merge")
    merge.add_argument("--repo", type=Path, default=Path.cwd())
    pair = commands.add_parser("validate-pair")
    pair.add_argument("--backend-digest", required=True)
    pair.add_argument("--frontend-digest", required=True)
    pair.add_argument("--rollback-backend-digest", required=True)
    pair.add_argument("--rollback-frontend-digest", required=True)
    pair.add_argument("--backend-target", required=True)
    pair.add_argument("--frontend-target", required=True)
    commands.add_parser("publish-pair")
    commands.add_parser("arm-demo")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-candidate":
            validate_owner_gates(dict(os.environ))
            validate_revisions(args.repo, args.trusted_revision, args.fault_revision)
            branch_tip = _git(
                args.repo, "rev-parse", "--verify",
                "refs/remotes/origin/demo/save-recovery",
            )
            if branch_tip != args.fault_revision:
                raise DemoGateError("Fault revision is not the current demo/save-recovery branch tip.")
            repaired_tree = expected_repaired_tree(
                args.repo, args.trusted_revision, args.fault_revision
            )
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                    output.write(f"expected_repaired_tree={repaired_tree}\n")
        elif args.command == "verify-merge":
            verify_merge(dict(os.environ), args.repo)
        elif args.command == "arm-demo":
            arm_demo(dict(os.environ), Path.cwd())
        elif args.command == "publish-pair":
            result = publish_image_pair(dict(os.environ))
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                    output.write(f"backend_digest={result['backend']}\n")
                    output.write(f"frontend_digest={result['frontend']}\n")
            print(json.dumps(result, sort_keys=True))
        else:
            validate_image_pair(
                backend_digest=args.backend_digest,
                frontend_digest=args.frontend_digest,
                rollback_backend_digest=args.rollback_backend_digest,
                rollback_frontend_digest=args.rollback_frontend_digest,
                backend_target=args.backend_target,
                frontend_target=args.frontend_target,
            )
    except (DemoGateError, OSError, subprocess.SubprocessError) as error:
        print(f"Development demo blocked: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"authorized": True, "command": args.command}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
