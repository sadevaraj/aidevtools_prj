"""Offline tests of the trusted T / faulty F repair and evidence boundary."""

import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from test_demo_control import demo_control, demo_repo, git, owner_environment
from test_repair_runner import (
    repair_runner, ROOT, MAIN_PATCH, TRUSTED_TEST_SOURCE, enabled_environment,
    INCIDENT, EXPIRY,
)

sys.path.insert(0, str(ROOT / "scripts"))


def context():
    return {
        "branch": demo_control.BRANCH, "trusted_revision": "a" * 40,
        "fault_revision": "b" * 40, "expected_repaired_tree": "c" * 40,
        "backend_digest": "sha256:" + "1" * 64,
        "frontend_digest": "sha256:" + "2" * 64,
        "rollback_backend_digest": "sha256:" + "3" * 64,
        "rollback_frontend_digest": "sha256:" + "4" * 64,
        "backend_target": demo_control.BACKEND_TARGET,
        "frontend_target": demo_control.FRONTEND_TARGET,
    }


def environment():
    return {
        **enabled_environment(), "DEMO_CONTROL_ENABLED": "true",
        **{"ALERT_REPAIR_AUTH_" + key.upper(): value for key, value in context().items()},
    }


@pytest.mark.parametrize("key,value", [
    ("branch", "feature"), ("trusted_revision", "main"), ("fault_revision", "a" * 40),
    ("expected_repaired_tree", ""), ("backend_digest", "latest"),
    ("frontend_digest", ""), ("rollback_backend_digest", "sha256:" + "1" * 64),
    ("backend_target", "https://kanban.invalid"),
    ("frontend_target", "https://attacker.invalid"),
])
def test_server_context_rejects_malformed_ref_image_rollback_and_targets(key, value):
    repair_runner.validate_demo_context(context())
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.validate_demo_context({**context(), key: value})


def test_candidate_runtime_mounts_only_workspace_and_trusted_readonly_instructions(tmp_path):
    command = repair_runner.isolated_copilot_command(
        tmp_path / "trusted", tmp_path / "candidate", ["--agent", "Prj_Coordinator"]
    )
    text = " ".join(command)
    for boundary in ("--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", "--pids-limit=128"):
        assert boundary in command
    assert "docker.sock" not in text
    assert "/home/runner" not in text
    assert "ACTIONS_ID_TOKEN" not in text
    assert "RENDER" not in text and "DATABASE" not in text and "PR_TOKEN" not in text
    assert text.count("--env") == 2  # Copilot job token and disposable home only.
    for path in (".github", "AGENTS.md", "README.md", "docs"):
        assert f"/workspace/{path},readonly" in text
    review = repair_runner.isolated_copilot_command(
        tmp_path, tmp_path, ["--agent", "Prj_QA"], readonly=True
    )
    assert f"type=bind,src={tmp_path},dst=/workspace,readonly" in review


def receipt(env, patch):
    return {
        "command": "sh scripts/test.sh", "returncode": 0,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "fault_revision": env["ALERT_REPAIR_AUTH_FAULT_REVISION"],
        "trusted_revision": env["ALERT_REPAIR_AUTH_TRUSTED_REVISION"],
        "repaired_tree": env["ALERT_REPAIR_AUTH_EXPECTED_REPAIRED_TREE"],
        "run_id": env["GITHUB_RUN_ID"], "run_attempt": env["GITHUB_RUN_ATTEMPT"],
    }


def test_mechanical_independent_sessions_bind_current_patch_and_actual_test_receipt(tmp_path, monkeypatch):
    env = environment()
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(MAIN_PATCH)
    tests = tmp_path / "tests.json"
    tests.write_text(json.dumps(receipt(env, MAIN_PATCH)))
    output = tmp_path / "evidence.json"
    calls = []

    def cli(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "--version":
            return SimpleNamespace(stdout=f"GitHub Copilot CLI {repair_runner.CLI_VERSION}.")
        role = command[command.index("--agent") + 1]
        assert "--deny-tool=write" in command
        assert "--deny-tool=shell" in command
        assert kwargs["env"]["GITHUB_TOKEN"] == env["GITHUB_TOKEN"]
        assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in kwargs["env"]
        assert role in ("Prj_QA", "Prj_Reviewer")
        return SimpleNamespace(stdout=json.dumps({
            "verdict": "PASS", "fault_revision": "b" * 40,
            "patch_sha256": hashlib.sha256(MAIN_PATCH).hexdigest(), "findings": [],
        }))

    evidence = repair_runner.collect_role_evidence(
        ROOT, patch, "b" * 40, output, environment=env, process_runner=cli,
        executable_finder=lambda *_args, **_kwargs: None, test_receipt=tests,
    )
    assert len(calls) == 3  # Version plus two separate processes, never self-asserted roles.
    assert evidence["roles"][0]["session_id"] != evidence["roles"][1]["session_id"]
    monkeypatch.setattr(repair_runner.os, "environ", env)
    repair_runner.verify_evidence_file(patch, output, "b" * 40)
    for key in ("run_id", "run_attempt", "trusted_revision", "repaired_tree", "returncode"):
        invalid = json.loads(output.read_text())
        invalid["tests"][key] = "stale"
        altered = tmp_path / "altered.json"
        altered.write_text(json.dumps(invalid))
        with pytest.raises(repair_runner.RepairGateError):
            repair_runner.verify_evidence_file(patch, altered, "b" * 40)
    patch.write_bytes(MAIN_PATCH + b"\n")
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.verify_evidence_file(patch, output, "b" * 40)


def test_missing_or_failed_tests_block_roles_before_any_provider_call(tmp_path):
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(MAIN_PATCH)
    with pytest.raises(repair_runner.RepairGateError, match="receipt"):
        repair_runner.collect_role_evidence(
            ROOT, patch, "b" * 40, tmp_path / "out.json", environment=environment(),
            process_runner=lambda *_args, **_kwargs: pytest.fail("No provider call permitted"),
        )


def test_exact_line_policy_rejects_lookalike_typo_repair_elsewhere():
    for invalid in (
        MAIN_PATCH.replace(b"game.board =", b"other.board ="),
        MAIN_PATCH.replace(b"puzzle.clues", b"untrusted.clues"),
        MAIN_PATCH.replace(b"+            game.board", b"+    game.board"),
    ):
        with pytest.raises(repair_runner.RepairGateError):
            repair_runner.validate_patch(invalid, TRUSTED_TEST_SOURCE)


def test_publication_rejects_moved_fault_before_credentials_are_used(tmp_path, monkeypatch):
    root, trusted, fault = demo_repo(tmp_path)
    env = environment()
    env.update({
        "PATH": os.environ["PATH"],
        "ALERT_REPAIR_PR_TOKEN": "offline-placeholder",
        "ALERT_REPAIR_AUTH_TRUSTED_REVISION": trusted,
        "ALERT_REPAIR_AUTH_FAULT_REVISION": fault,
    })
    (root / "extra").write_text("moved")
    git(root, "add", ".")
    git(root, "commit", "-m", "ref moved")
    monkeypatch.setattr(repair_runner.os, "environ", env)
    with pytest.raises(repair_runner.RepairGateError, match="moved"):
        repair_runner.publish_pr(root, INCIDENT, EXPIRY, tmp_path / "unused.patch")


@pytest.mark.parametrize("expiry", ["", "invalid", "2020-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"])
def test_fault_window_rejects_missing_expired_or_excessive_ttl(expiry):
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_owner_gates({**owner_environment(), "DEMO_EXPIRES_AT": expiry})


def test_workflows_keep_fault_red_and_segregate_tooling_candidate_and_publisher():
    fault = yaml.load(
        (ROOT / ".github/workflows/pipeline.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(fault["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert "inputs.mode == 'fault'" in fault["jobs"]["authorize-fault"]["if"]
    for name in ("reproduce-fault", "build-fault-images"):
        job = fault["jobs"][name]
        assert job["permissions"] == {"contents": "read"}
        assert "secrets." not in json.dumps(job)
    publisher = fault["jobs"]["publish-fault-images"]
    assert "docker/build-push-action" not in json.dumps(publisher)
    assert "publish-pair" in json.dumps(publisher)
    repair = fault
    assert repair["env"]["DEMO_CONTROL_REQUIRED"] == "true"
    assert "id-token" not in repair["jobs"]["candidate"]["permissions"]
    assert "test-candidate" in json.dumps(repair["jobs"]["verify"])
    assert "working-directory" not in next(
        step for step in repair["jobs"]["verify"]["steps"]
        if "test-candidate" in step.get("run", "")
    )
    for name in ("candidate", "verify", "publish-pr"):
        job = repair["jobs"][name]
        assert job["defaults"]["run"]["working-directory"] == "tooling"
        checkouts = [
            step["with"] for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        assert checkouts[0]["path"] == "tooling"
        assert checkouts[0]["ref"] == "${{ needs.authorization.outputs.trusted_revision }}"
        for checkout in checkouts:
            assert "runner.temp" not in checkout.get("path", "")
