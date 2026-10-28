"""Approved #20 replacement: offline gates, never a provider or remote write."""

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import yaml

from test_repair_runner import ROOT, MAIN_PATCH, INCIDENT, enabled_environment, repair_runner as runner


REVISION = "a" * 40
TREE = "b" * 40


def receipt(env):
    return {
        "command": "sh scripts/test.sh", "returncode": 0,
        "patch_sha256": hashlib.sha256(MAIN_PATCH).hexdigest(),
        "fault_revision": REVISION, "repaired_tree": TREE,
        "run_id": env["GITHUB_RUN_ID"], "run_attempt": env["GITHUB_RUN_ATTEMPT"],
        "unverified_access_one_attempt_approved": False,
    }


def reports():
    return [
        {
            "role": role, "verdict": "PASS", "fault_revision": REVISION,
            "patch_sha256": hashlib.sha256(MAIN_PATCH).hexdigest(),
            "independent": True, "session_id": f"session-{index}-independent",
            "findings": [],
        }
        for index, role in enumerate(("Prj_QA", "Prj_Reviewer"))
    ]


def test_only_normal_delivery_and_bounded_repair_jobs_remain():
    workflow = yaml.load((ROOT / ".github/workflows/pipeline.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["jobs"]) == {
        "tests", "publish", "deploy-development", "authorization", "candidate", "verify", "publish-pr",
    }
    assert workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["options"] == ["repair"]
    assert workflow["jobs"]["publish"]["needs"] == "tests"
    assert set(workflow["jobs"]["deploy-development"]["needs"]) == {"tests", "publish"}
    for path in [ROOT / ".github/workflows/pipeline.yml", *list((ROOT / "scripts").glob("*.py"))]:
        source = path.read_text()
        assert "DEMO_" not in source
        assert "demo_control" not in source
        assert "evidenceURL" not in source
    for job in ("candidate", "verify", "publish-pr"):
        assert "needs.authorization.outputs.deadline" in workflow["jobs"][job]["env"]["ALERT_REPAIR_DEADLINE"]
    assert "RENDER_API_KEY" not in str(workflow["jobs"]["candidate"])
    assert "ALERT_REPAIR_PR_TOKEN" not in str(workflow["jobs"]["verify"])


def test_removed_routes_and_settings_are_not_runtime_controls():
    # Container layout differs from the checkout.
    backend = ROOT / "backend/app" if (ROOT / "backend/app").exists() else ROOT / "app"
    source = (backend / "main.py").read_text()
    assert "/api/alerts/demo/" not in source
    assert "body.borad" not in source
    assert "DEMO_" not in (backend / "config.py").read_text()


@pytest.mark.parametrize("delta", [-1, 0, 901, 3600])
def test_expired_or_oversized_deadlines_stop(delta):
    with pytest.raises(runner.RepairGateError):
        runner.remaining_seconds({
            "ALERT_REPAIR_DEADLINE": (datetime.now(timezone.utc) + timedelta(seconds=delta)).isoformat()
        })


@pytest.mark.parametrize("field,value", [
    ("returncode", 1), ("patch_sha256", "c" * 64), ("fault_revision", "c" * 40),
    ("run_attempt", "2"), ("run_id", "5678"), ("repaired_tree", ""),
    ("unverified_access_one_attempt_approved", True),
])
def test_same_candidate_test_receipt_cannot_be_substituted(field, value):
    env = enabled_environment()
    stale = {**receipt(env), field: value}
    with pytest.raises(runner.RepairGateError):
        runner.validate_test_receipt_data(stale, hashlib.sha256(MAIN_PATCH).hexdigest(), REVISION, env)


@pytest.mark.parametrize("field,value", [
    ("verdict", "CHANGES_REQUESTED"), ("fault_revision", "c" * 40),
    ("patch_sha256", "c" * 64), ("independent", False),
    ("findings", ["blocking"]), ("role", "Prj_Dev"),
])
def test_independent_current_candidate_role_evidence_is_mandatory(field, value):
    qa, reviewer = reports()
    qa[field] = value
    with pytest.raises(runner.RepairGateError):
        runner.validate_role_evidence(qa, reviewer, REVISION, hashlib.sha256(MAIN_PATCH).hexdigest())


def test_role_sessions_must_be_distinct():
    qa, reviewer = reports()
    reviewer["session_id"] = qa["session_id"]
    with pytest.raises(runner.RepairGateError):
        runner.validate_role_evidence(qa, reviewer, REVISION, qa["patch_sha256"])


def test_actual_distinct_isolated_review_processes_bind_receipt(tmp_path):
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(MAIN_PATCH)
    env = enabled_environment()
    test_receipt = tmp_path / "receipt.json"
    test_receipt.write_text(json.dumps(receipt(env)))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "--version":
            return SimpleNamespace(stdout=f"GitHub Copilot CLI {runner.CLI_VERSION}.")
        role = command[command.index("--agent") + 1]
        assert command[0:2] == ["docker", "run"]
        assert "--deny-tool=write" in command
        assert "--deny-tool=shell" in command
        assert kwargs["env"]["GITHUB_TOKEN"] == env["GITHUB_TOKEN"]
        assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in kwargs["env"]
        assert '"returncode": 0' in command[command.index("--prompt") + 1]
        return SimpleNamespace(stdout=json.dumps(next(r for r in reports() if r["role"] == role)))

    result = runner.collect_role_evidence(
        ROOT, patch, REVISION, tmp_path / "evidence.json", env,
        process_runner=fake_run, test_receipt=test_receipt,
    )
    assert len(calls) == 3  # version only, then two real review invocations
    assert len({r["session_id"] for r in result["roles"]}) == 2
    assert result["tests"] == receipt(env)


def test_missing_test_receipt_stops_before_review_provider(tmp_path):
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(MAIN_PATCH)
    with pytest.raises(runner.RepairGateError, match="receipt"):
        runner.collect_role_evidence(
            ROOT, patch, REVISION, tmp_path / "evidence.json", enabled_environment(),
            process_runner=lambda *_a, **_kw: pytest.fail("No provider invocation allowed"),
        )


@pytest.mark.parametrize("key", ["ALERT_REPAIR_ENABLED", "REPAIR_NO_OVERAGE_CONFIRMED", "REPAIR_PROVIDER_TRANSMISSION_APPROVED", "ALERT_REPAIR_AUTHORIZED"])
def test_review_provider_cannot_bypass_runtime_gates(tmp_path, key):
    env = {**enabled_environment(), key: "false"}
    with pytest.raises(runner.RepairGateError):
        runner.collect_role_evidence(
            ROOT, tmp_path / "absent.patch", REVISION, tmp_path / "evidence.json", env,
            process_runner=lambda *_a, **_kw: pytest.fail("No provider invocation allowed"),
        )


def test_verified_evidence_file_requires_full_current_test_receipt(tmp_path, monkeypatch):
    env = enabled_environment()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(MAIN_PATCH)
    evidence = {
        "fault_revision": REVISION, "patch_sha256": hashlib.sha256(MAIN_PATCH).hexdigest(),
        "roles": reports(), "tests": receipt(env),
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence))
    runner.verify_evidence_file(patch, path, REVISION)
    evidence.pop("tests")
    path.write_text(json.dumps(evidence))
    with pytest.raises(runner.RepairGateError):
        runner.verify_evidence_file(patch, path, REVISION)


def check_data():
    return {
        "headRefOid": TREE, "baseRefOid": REVISION, "isDraft": False, "reviewDecision": "",
        "statusCheckRollup": [{
            "name": "tests", "workflowName": "Sudoku pipeline",
            "status": "COMPLETED", "conclusion": "SUCCESS",
        }],
    }


@pytest.mark.parametrize("case", ["success", "failure", "changed-head", "changed-base", "review-blocked", "permissions"])
def test_auto_merge_is_after_checks_only_and_never_bypasses_protection(tmp_path, case):
    env = {**enabled_environment(), "ALERT_REPAIR_PR_TOKEN": "offline-only"}
    data = check_data()
    if case == "failure":
        data["statusCheckRollup"][0]["conclusion"] = "FAILURE"
    if case == "changed-head":
        data["headRefOid"] = "c" * 40
    if case == "changed-base":
        data["baseRefOid"] = "c" * 40
    if case == "review-blocked":
        data["reviewDecision"] = "CHANGES_REQUESTED"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "git":
            return SimpleNamespace(stdout=TREE)
        if "view" in command:
            return SimpleNamespace(stdout=json.dumps(data))
        assert "--auto" in command and "--match-head-commit" in command
        assert "--admin" not in command and "--force" not in command
        return SimpleNamespace(returncode=1 if case == "permissions" else 0)

    if case == "success":
        runner.merge_after_checks(tmp_path, "https://github.com/sadevaraj/aidevtools_prj/pull/42", env, REVISION, runner=fake_run)
        assert len(calls) == 3
    else:
        with pytest.raises(runner.RepairGateError):
            runner.merge_after_checks(tmp_path, "https://github.com/sadevaraj/aidevtools_prj/pull/42", env, REVISION, runner=fake_run)
        if case != "permissions":
            assert not any("merge" in c for c in calls)


def test_empty_or_pending_checks_time_out_without_merge(tmp_path, monkeypatch):
    env = {**enabled_environment(), "ALERT_REPAIR_PR_TOKEN": "offline-only"}
    data = check_data()
    data["statusCheckRollup"] = []
    budget = iter([1, 0])
    monkeypatch.setattr(runner, "remaining_seconds", lambda _env: next(budget) or (_ for _ in ()).throw(runner.RepairGateError("expired")))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=TREE if command[0] == "git" else json.dumps(data))

    with pytest.raises(runner.RepairGateError):
        runner.merge_after_checks(tmp_path, "https://github.com/sadevaraj/aidevtools_prj/pull/42", env, REVISION, runner=fake_run)
    assert not any("merge" in c for c in calls)


@pytest.mark.parametrize("case", ["success", "wrong-tree", "wrong-revision", "test-failure"])
def test_full_harness_runs_on_exact_candidate_not_unmodified_tooling(tmp_path, monkeypatch, case):
    env = {**enabled_environment(), "GITHUB_SHA": REVISION,
           "DATABASE_URL": "not-a-live-value", "ACTIONS_RUNTIME_TOKEN": "offline-only"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    trusted = tmp_path / "trusted"
    candidate = tmp_path / "candidate"
    trusted.mkdir()
    candidate.mkdir()
    # Keep the actual pinned trusted test; no copied/generated candidate test.
    trusted_test = runner._regression_test_path(ROOT)
    monkeypatch.setattr(runner, "_regression_test_path", lambda _root: trusted_test)
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(MAIN_PATCH)
    output = tmp_path / "receipt.json"
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "sh":
            assert kwargs["cwd"] == candidate
            assert "GITHUB_TOKEN" not in kwargs["env"]
            assert "ACTIONS_RUNTIME_TOKEN" not in kwargs["env"]
            assert "DATABASE_URL" not in kwargs["env"]
            if case == "test-failure":
                raise subprocess.CalledProcessError(1, command)
            return SimpleNamespace(returncode=0)
        if "rev-parse" in command:
            return SimpleNamespace(stdout=("c" * 40 if case == "wrong-revision" else REVISION))
        if "--cached" in command:
            return SimpleNamespace(stdout="unreviewed-patch" if case == "wrong-tree" else MAIN_PATCH.decode())
        if "write-tree" in command:
            return SimpleNamespace(stdout=TREE)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    if case == "success":
        runner.test_repaired_candidate(trusted, candidate, patch, output)
        assert json.loads(output.read_text()) == receipt(env)
    else:
        with pytest.raises((runner.RepairGateError, subprocess.CalledProcessError)):
            runner.test_repaired_candidate(trusted, candidate, patch, output)
        assert not output.exists()
        if case != "test-failure":
            assert not any(command[0] == "sh" for command, _kwargs in calls)


@pytest.mark.parametrize("case", ["success", "moved-main", "wrong-tree", "wrong-checkout"])
def test_publisher_only_applies_tested_tree_and_never_executes_candidate(tmp_path, monkeypatch, case):
    env = {**enabled_environment(), "GITHUB_SHA": REVISION,
           "ALERT_REPAIR_PR_TOKEN": "offline-only"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(MAIN_PATCH)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({
        "fault_revision": REVISION, "patch_sha256": hashlib.sha256(MAIN_PATCH).hexdigest(),
        "roles": reports(), "tests": receipt(env),
    }))
    calls = []
    committed = False

    def fake_run(command, **kwargs):
        nonlocal committed
        calls.append(command)
        assert command[0] in {"git", "gh"}
        assert all("offline-only" not in str(arg) for arg in command)
        if command[0] == "git":
            assert "GITHUB_TOKEN" not in kwargs["env"]
            if "rev-parse" in command:
                return SimpleNamespace(stdout=TREE if committed or case == "wrong-checkout" else REVISION)
            if "write-tree" in command:
                return SimpleNamespace(stdout="c" * 40 if case == "wrong-tree" else TREE)
            if "ls-remote" in command:
                return SimpleNamespace(stdout=f"{'c' * 40 if case == 'moved-main' else REVISION}\trefs/heads/main")
            if "commit" in command:
                committed = True
            return SimpleNamespace(stdout="", returncode=0)
        assert kwargs["env"]["GH_TOKEN"] == "offline-only"
        if "create" in command:
            return SimpleNamespace(stdout="https://github.com/sadevaraj/aidevtools_prj/pull/42\n")
        if "view" in command:
            return SimpleNamespace(stdout=json.dumps(check_data()))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    if case == "success":
        runner.publish_pr(tmp_path, INCIDENT, env["ALERT_REPAIR_AUTH_EXPIRES_AT"], patch,
                          trusted_root=ROOT, evidence_path=evidence)
        assert any("create" in c for c in calls)
        assert any("merge" in c for c in calls)
    else:
        with pytest.raises(runner.RepairGateError):
            runner.publish_pr(tmp_path, INCIDENT, env["ALERT_REPAIR_AUTH_EXPIRES_AT"], patch,
                              trusted_root=ROOT, evidence_path=evidence)
        assert not any("push" in c or "create" in c or "merge" in c for c in calls)
