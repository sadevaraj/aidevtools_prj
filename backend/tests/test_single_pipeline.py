"""Offline MAIN-only workflow trust, mode, migration and known-fault boundaries."""

import json

import pytest
import yaml

from test_demo_control import ROOT, demo_control, demo_repo, git, owner_environment


def workflow():
    return yaml.load((ROOT / ".github/workflows/pipeline.yml").read_text(), Loader=yaml.BaseLoader)


def test_single_workflow_preserves_red_normal_gates_and_exact_separate_exception():
    w = workflow()
    assert sorted(p.name for p in (ROOT / ".github/workflows").glob("*.yml")) == ["pipeline.yml"]
    assert w["on"]["push"]["branches"] == ["main"]
    assert set(w["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert w["on"]["workflow_dispatch"]["inputs"]["mode"]["options"] == ["fault", "repair"]
    assert not any(name in w["on"] for name in ("workflow_run", "pull_request_target"))
    assert w["jobs"]["publish"]["needs"] == "tests"
    assert w["jobs"]["deploy-development"]["needs"] == ["tests", "publish"]
    text = json.dumps(w)
    assert "continue-on-error" not in text and "failure()" not in text
    assert "demo/save-recovery" not in text
    for name in ("publish", "deploy-development"):
        gate = w["jobs"][name]["if"]
        assert "github.event_name == 'push'" in gate and "github.ref == 'refs/heads/main'" in gate
        assert "always()" not in gate
    for name, mode in (("authorize-fault", "fault"), ("authorization", "repair")):
        job = w["jobs"][name]
        assert "github.event_name == 'workflow_dispatch'" in job["if"]
        assert f"inputs.mode == '{mode}'" in job["if"]
        assert "github.repository == 'sadevaraj/aidevtools_prj'" in job["if"]
        assert "github.ref == 'refs/heads/main'" in job["if"]
        assert "fullmatch" in job["steps"][0]["run"]
        checkout = job["steps"][1]["with"]
        assert checkout["ref"] == "${{ vars.DEMO_TRUSTED_REVISION }}"
        assert checkout["fetch-depth"] == "0"
    assert "verify-runtime" in json.dumps(w["jobs"]["authorization"])
    assert "verify-candidate" in json.dumps(w["jobs"]["authorize-fault"])
    assert w["jobs"]["reproduce-fault"]["needs"] == "authorize-fault"
    assert w["jobs"]["build-fault-images"]["needs"] == ["authorize-fault", "reproduce-fault"]
    assert w["jobs"]["publish-fault-images"]["needs"] == ["authorize-fault", "build-fault-images"]
    assert w["jobs"]["deploy-fault-pair"]["needs"] == ["authorize-fault", "publish-fault-images"]
    assert w["jobs"]["deploy-fault-pair"]["environment"] == "sudoku-development"
    assert "github.actor == 'sadevaraj'" in w["jobs"]["authorize-fault"]["if"]


def runtime_env(root, trusted, fault):
    git(root, "update-ref", "refs/remotes/origin/main", fault)
    git(root, "checkout", "--detach", trusted)
    return {
        **owner_environment(), "GITHUB_SHA": fault, "GITHUB_WORKFLOW_SHA": fault,
    }


@pytest.mark.parametrize("mode", ["fault", "repair"])
def test_exact_fault_main_workflow_can_use_immutable_healthy_tooling(tmp_path, mode):
    root, trusted, fault = demo_repo(tmp_path)
    env = {**runtime_env(root, trusted, fault), "PIPELINE_MODE": mode}
    demo_control.validate_runtime(env, root, trusted, fault)


@pytest.mark.parametrize("key,value", [
    ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_EVENT_NAME", "workflow_run"),
    ("GITHUB_REF", "refs/pull/42/merge"), ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_REPOSITORY", "fork/repo"), ("GITHUB_WORKFLOW_REF", "other"),
    ("GITHUB_WORKFLOW_SHA", "a" * 40), ("GITHUB_SHA", "a" * 40),
    ("PIPELINE_MODE", ""), ("PIPELINE_MODE", "normal"),
])
def test_wrong_event_ref_fork_mode_or_workflow_revision_fails_closed(tmp_path, key, value):
    root, trusted, fault = demo_repo(tmp_path)
    env = {**runtime_env(root, trusted, fault), key: value}
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_runtime(env, root, trusted, fault)


def test_changed_workflow_or_unpinned_tooling_is_not_a_supported_fault(tmp_path):
    root, trusted, fault = demo_repo(tmp_path)
    env = runtime_env(root, trusted, fault)
    git(root, "checkout", "main")
    (root / "workflow.yml").write_text("unapproved")
    git(root, "add", ".")
    git(root, "commit", "-m", "unsupported")
    moved = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/main", moved)
    git(root, "checkout", "--detach", trusted)
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_runtime(
            {**env, "GITHUB_SHA": moved, "GITHUB_WORKFLOW_SHA": moved}, root, trusted, moved,
        )
    git(root, "update-ref", "refs/remotes/origin/main", fault)
    git(root, "checkout", "--detach", fault)
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_runtime(env, root, trusted, fault)


@pytest.mark.parametrize("key,value", [
    ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_RUN_ID", ""),
    ("PIPELINE_MODE", "repair"), ("DEMO_FAULT_ENABLED", ""),
    ("GITHUB_ACTOR", "collaborator"),
])
def test_fault_owner_dispatch_is_first_attempt_only(key, value):
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_owner_gates({**owner_environment(), key: value})


def test_migration_chain_preserves_receiver_and_historical_demo_migrations():
    # Also asserted against real PostgreSQL in test_demo_authorization.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_current_head() == "0004_main_demo"
    assert script.get_revision("0004_main_demo").down_revision == "0003_demo_authorization"
    assert script.get_revision("0003_demo_authorization").down_revision == "0002_alert_incidents"
    assert script.get_revision("0002_alert_incidents").down_revision == "0001_core_tables"
