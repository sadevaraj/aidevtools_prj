"""Offline guard tests for the one approved development save-recovery demo."""

import importlib.util
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "scripts/demo_control.py").exists():
    ROOT = Path("/app")
SPEC = importlib.util.spec_from_file_location(
    "demo_control", ROOT / "scripts" / "demo_control.py"
)
demo_control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo_control)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def demo_repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "source"
    root.mkdir(parents=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Offline Test")
    git(root, "config", "user.email", "offline@example.invalid")
    path = root / demo_control.SOURCE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(
        "def save_game():\n    " + demo_control.CORRECT_LINE + "\n",
        encoding="utf-8",
    )
    git(root, "add", ".")
    git(root, "commit", "-m", "healthy")
    trusted = git(root, "rev-parse", "HEAD")
    git(root, "checkout", demo_control.BRANCH)
    path.write_text(
        "def save_game():\n    " + demo_control.FAULT_LINE + "\n",
        encoding="utf-8",
    )
    git(root, "commit", "-am", "approved fault")
    fault = git(root, "rev-parse", "HEAD")
    return root, trusted, fault


def owner_environment():
    return {
        "DEMO_FAULT_ENABLED": "true",
        "DEMO_ROLLBACK_PAIR_VERIFIED": "true",
        "DEMO_WINDOW_CONFIRMED": "true",
        "DEMO_IMAGE_PROVENANCE_VERIFIED": "true",
        "DEMO_TARGETS_CONFIRMED": "true",
        "DEMO_EXPIRES_AT": (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat(),
        "DEMO_ROLLBACK_EVIDENCE_URL":
            "https://github.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-6430240332",
        "GITHUB_REPOSITORY": demo_control.REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "PIPELINE_MODE": "fault",
        "GITHUB_WORKFLOW_REF": demo_control.WORKFLOW_REF,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_ACTOR": "sadevaraj",
    }


def test_candidate_accepts_only_exact_approved_one_line_descendant(tmp_path):
    root, trusted, fault = demo_repo(tmp_path)
    demo_control.validate_revisions(root, trusted, fault)
    assert demo_control.expected_repaired_tree(root, trusted, fault) == git(
        root, "rev-parse", f"{trusted}^{{tree}}"
    )


@pytest.mark.parametrize(
    ("trusted", "fault"),
    [
        ("bad", "a" * 40),
        ("a" * 40, "a" * 40),
        ("0" * 40, "f" * 40),
    ],
)
def test_candidate_rejects_malformed_identical_or_unavailable_revisions(
    tmp_path, trusted, fault
):
    root, _, _ = demo_repo(tmp_path)
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_revisions(root, trusted, fault)


def test_candidate_rejects_wrong_line_extra_commit_and_extra_path(tmp_path):
    root, trusted, fault = demo_repo(tmp_path)
    path = root / demo_control.SOURCE_PATH
    path.write_text("def save():\n    pass\n", encoding="utf-8")
    git(root, "commit", "-am", "unsupported")
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_revisions(root, trusted, git(root, "rev-parse", "HEAD"))

    root, trusted, _fault = demo_repo(tmp_path / "second")
    extra = root / "README.md"
    extra.write_text("not allowed\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "extra path")
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_revisions(root, trusted, git(root, "rev-parse", "HEAD"))


def test_candidate_requires_all_owner_gates_and_verified_rollback_evidence():
    env = owner_environment()
    demo_control.validate_owner_gates(env)
    for key in (
        "DEMO_FAULT_ENABLED",
        "DEMO_ROLLBACK_PAIR_VERIFIED",
        "DEMO_WINDOW_CONFIRMED",
        "DEMO_IMAGE_PROVENANCE_VERIFIED",
        "DEMO_TARGETS_CONFIRMED",
    ):
        blocked = dict(env, **{key: "false"})
        with pytest.raises(demo_control.DemoGateError):
            demo_control.validate_owner_gates(blocked)
    with pytest.raises(demo_control.DemoGateError):
        demo_control.validate_owner_gates(
            dict(env, DEMO_ROLLBACK_EVIDENCE_URL="https://attacker.invalid/")
        )


def test_digest_pair_requires_immutable_pair_and_exact_development_targets():
    values = {
        "backend_digest": "sha256:" + "1" * 64,
        "frontend_digest": "sha256:" + "2" * 64,
        "rollback_backend_digest": "sha256:" + "3" * 64,
        "rollback_frontend_digest": "sha256:" + "4" * 64,
        "backend_target": demo_control.BACKEND_TARGET,
        "frontend_target": demo_control.FRONTEND_TARGET,
    }
    demo_control.validate_image_pair(**values)
    for key, value in (
        ("backend_digest", "latest"),
        ("frontend_target", "https://kanban.example.invalid"),
        ("rollback_backend_digest", values["backend_digest"]),
    ):
        invalid = dict(values, **{key: value})
        with pytest.raises(demo_control.DemoGateError):
            demo_control.validate_image_pair(**invalid)


def test_role_evidence_must_be_distinct_current_and_bound_to_exact_patch():
    reports = [
        {
            "role": role,
            "verdict": "PASS",
            "fault_revision": "a" * 40,
            "patch_sha256": "b" * 64,
            "independent": True,
            "session_id": session_id,
            "findings": [],
        }
        for role, session_id in (("Prj_QA", "qa-session-0001"), ("Prj_Reviewer", "review-session-01"))
    ]
    demo_control.validate_role_evidence(
        reports[0], reports[1], fault_revision="a" * 40, patch_sha256="b" * 64
    )
    for changed in (
        dict(reports[0], fault_revision="c" * 40),
        dict(reports[0], independent=False),
        dict(reports[0], findings=["blocking"]),
        dict(reports[0], verdict="CHANGES_REQUESTED"),
        dict(reports[0], session_id=reports[1]["session_id"]),
    ):
        with pytest.raises(demo_control.DemoGateError):
            demo_control.validate_role_evidence(
                changed, reports[1], fault_revision="a" * 40, patch_sha256="b" * 64
            )


def test_repaired_merge_gate_rejects_main_unknown_tree_wrong_target_and_disabled(tmp_path):
    root, trusted, fault = demo_repo(tmp_path)
    expected = demo_control.expected_repaired_tree(root, trusted, fault)
    env = {
        "GITHUB_REPOSITORY": demo_control.REPOSITORY,
        "GITHUB_REF": f"refs/heads/{demo_control.BRANCH}",
        "GITHUB_EVENT_NAME": "push",
        "DEMO_RECOVERY_ENABLED": "true",
        "DEMO_EXPECTED_REPAIRED_TREE": expected,
        "DEMO_TRUSTED_REVISION": trusted,
        "DEMO_FAULT_REVISION": fault,
        "DEMO_EXPIRES_AT": (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat(),
    }
    # A merge/push tree is checked only after the fault branch has been repaired.
    git(root, "checkout", demo_control.BRANCH)
    git(root, "checkout", "-b", "repair")
    (root / demo_control.SOURCE_PATH).write_text(
        "def save_game():\n    " + demo_control.CORRECT_LINE + "\n", encoding="utf-8"
    )
    git(root, "commit", "-am", "repair")
    git(root, "checkout", demo_control.BRANCH)
    git(root, "merge", "--no-ff", "repair", "-m", "manual repair merge")
    expected = git(root, "rev-parse", "HEAD^{tree}")
    env["DEMO_EXPECTED_REPAIRED_TREE"] = expected
    demo_control.verify_merge(env, root)
    for key, value in (
        ("GITHUB_REF", "refs/heads/feature"),
        ("DEMO_RECOVERY_ENABLED", "false"),
        ("DEMO_EXPECTED_REPAIRED_TREE", "0" * 40),
        ("DEMO_FAULT_REVISION", trusted),
        ("DEMO_EXPIRES_AT", "expired"),
    ):
        with pytest.raises(demo_control.DemoGateError):
            demo_control.verify_merge(dict(env, **{key: value}), root)


@pytest.mark.parametrize("bad_provenance", [True, False])
def test_image_publication_checks_labels_and_records_registry_pair_without_running_images(
    monkeypatch, bad_provenance,
):
    calls = []
    def docker(command, **_kwargs):
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(stdout=json.dumps({
                "org.opencontainers.image.source": f"https://github.com/{demo_control.REPOSITORY}",
                "org.opencontainers.image.revision": "0" * 40 if bad_provenance else "a" * 40,
            }))
        return SimpleNamespace(stdout="fixture: digest: sha256:" + "1" * 64 + " size: 123\n")
    monkeypatch.setattr(demo_control.subprocess, "run", docker)
    env = {"DEMO_FAULT_REVISION": "a" * 40, "GITHUB_REPOSITORY": demo_control.REPOSITORY}
    if bad_provenance:
        with pytest.raises(demo_control.DemoGateError, match="provenance"):
            demo_control.publish_image_pair(env)
        assert not any(command[1] == "push" for command in calls)
    else:
        assert demo_control.publish_image_pair(env) == {
            "backend": "sha256:" + "1" * 64, "frontend": "sha256:" + "1" * 64,
        }
        assert len([command for command in calls if command[1] == "push"]) == 2
    assert not any(command[1] in ("run", "build") for command in calls)


def test_owner_arm_uses_only_fixed_endpoint_and_exact_built_pair(tmp_path):
    root, trusted, fault = demo_repo(tmp_path)
    git(root, "update-ref", "refs/remotes/origin/main", fault)
    git(root, "checkout", "--detach", trusted)
    env = {
        **owner_environment(), "TRUSTED_REVISION": trusted, "FAULT_REVISION": fault,
        "GITHUB_SHA": fault, "GITHUB_WORKFLOW_SHA": fault,
        "BACKEND_DIGEST": "sha256:" + "1" * 64,
        "FRONTEND_DIGEST": "sha256:" + "2" * 64,
        "DEMO_ROLLBACK_BACKEND_DIGEST": "sha256:" + "3" * 64,
        "DEMO_ROLLBACK_FRONTEND_DIGEST": "sha256:" + "4" * 64,
        "DEMO_CONTROL_TOKEN": "offline-demo-owner-secret-only",
    }
    calls = []
    class Response:
        status = 201
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self, size):
            assert size == 4097
            return json.dumps({
                "armed": True, "trusted_revision": trusted, "fault_revision": fault,
                "expected_repaired_tree": git(root, "rev-parse", f"{trusted}^{{tree}}"),
                "branch": demo_control.BRANCH,
            }).encode()
    def opener(request, **_kwargs):
        calls.append(request)
        assert request.full_url == demo_control.BACKEND_TARGET + "/api/alerts/demo/arm"
        body = json.loads(request.data)
        assert body["fault_revision"] == fault
        assert body["backend_digest"] == env["BACKEND_DIGEST"]
        assert "command" not in body and "url" not in body
        return Response()
    demo_control.arm_demo(env, root, opener=opener)
    assert len(calls) == 1
    git(root, "update-ref", "refs/remotes/origin/main", trusted)
    with pytest.raises(demo_control.DemoGateError, match="bind"):
        demo_control.arm_demo(env, root, opener=opener)
    assert len(calls) == 1
