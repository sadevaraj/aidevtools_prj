"""Offline tests for the owner-gated Copilot execution and patch boundary."""

import importlib.util
from datetime import datetime, timedelta, timezone
import json
import io
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "scripts/repair_runner.py").exists():
    ROOT = Path("/app")
spec = importlib.util.spec_from_file_location(
    "repair_runner", ROOT / "scripts/repair_runner.py"
)
repair_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair_runner)

INCIDENT = "a" * 64
EXPIRY = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
PATCH = b"""diff --git a/backend/app/main.py b/backend/app/main.py
index 1111111..2222222 100644
--- a/backend/app/main.py
+++ b/backend/app/main.py
@@ -324,1 +324,1 @@
-            game.board = _validated_board(body.borad, puzzle.clues)
+            game.board = _validated_board(body.board, puzzle.clues)
diff --git a/backend/tests/test_api.py b/backend/tests/test_api.py
index 3333333..4444444 100644
--- a/backend/tests/test_api.py
+++ b/backend/tests/test_api.py
@@ -100,0 +101,5 @@
+def test_deliberate_save_typo_reproduces_500_and_repaired_save_persists(tmp_path):
+    assert response.status_code == 500
+    assert persisted.last_saved_at is None
+    assert saved.status_code == 200
+    assert persisted.board == board
"""
# PATCH deliberately retains the original marker-only candidate test, including
# QA's unchanged injection reproducer below. It is no longer an allowed patch.
MAIN_PATCH = PATCH.split(b"diff --git a/backend/tests/test_api.py", 1)[0]
TRUSTED_TEST_SOURCE = repair_runner._regression_test_path(ROOT).read_text(encoding="utf-8")


def enabled_environment():
    return {
        "ALERT_REPAIR_ENABLED": "true",
        "REPAIR_COPILOT_OWNER_ENABLED": "true",
        "REPAIR_FREE_ENTITLEMENT_CONFIRMED": "true",
        "REPAIR_QUOTA_CONFIRMED": "true",
        "REPAIR_NO_OVERAGE_CONFIRMED": "true",
        "REPAIR_PROVIDER_TRANSMISSION_APPROVED": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": "sadevaraj/aidevtools_prj",
        "GITHUB_REF": "refs/heads/main",
        "PIPELINE_MODE": "repair",
        "GITHUB_WORKFLOW_REF": "sadevaraj/aidevtools_prj/.github/workflows/pipeline.yml@refs/heads/main",
        "ALERT_REPAIR_DEADLINE": (datetime.now(timezone.utc) + timedelta(minutes=14)).isoformat(),
        "GITHUB_TOKEN": "offline-only-token",
        "ALERT_REPAIR_AUTHORIZED": "true",
        "GITHUB_RUN_ID": "1234",
        "GITHUB_RUN_ATTEMPT": "1",
        "ALERT_REPAIR_AUTH_RUN_ID": "1234",
        "ALERT_REPAIR_AUTH_RUN_ATTEMPT": "1",
        "ALERT_REPAIR_AUTH_INCIDENT_ID": INCIDENT,
        "ALERT_REPAIR_AUTH_EXPIRES_AT": EXPIRY,
        "ALERT_REPAIR_AUTH_URL": repair_runner.CLAIM_URL,
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://actions.example.test/oidc?api-version=2.0",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "offline-oidc-request-token",
        "PATH": "/offline",
    }


def test_runner_is_disabled_without_explicit_owner_free_quota_and_privacy_gates():
    env = enabled_environment()
    for key in (
        "REPAIR_COPILOT_OWNER_ENABLED",
        "ALERT_REPAIR_ENABLED",
        "REPAIR_FREE_ENTITLEMENT_CONFIRMED",
        "REPAIR_QUOTA_CONFIRMED",
        "REPAIR_NO_OVERAGE_CONFIRMED",
        "REPAIR_PROVIDER_TRANSMISSION_APPROVED",
    ):
        blocked = dict(env)
        blocked[key] = "false"
        with pytest.raises(repair_runner.RepairGateError):
            repair_runner.require_enabled(blocked, INCIDENT, EXPIRY)


def unverified_access_environment():
    env = enabled_environment()
    env.pop("REPAIR_FREE_ENTITLEMENT_CONFIRMED")
    env.pop("REPAIR_QUOTA_CONFIRMED")
    return {
        **env,
        "REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED": "true",
        "PIPELINE_MODE": "repair",
        "GITHUB_WORKFLOW_REF":
            "sadevaraj/aidevtools_prj/.github/workflows/pipeline.yml@refs/heads/main",
    }


@pytest.mark.parametrize("confirmation", [None, "", "false", "unknown"])
def test_explicit_controlled_access_risk_does_not_fabricate_confirmations(confirmation):
    env = unverified_access_environment()
    if confirmation is not None:
        env["REPAIR_FREE_ENTITLEMENT_CONFIRMED"] = confirmation
        env["REPAIR_QUOTA_CONFIRMED"] = confirmation
    before = dict(env)
    repair_runner.require_enabled(env, INCIDENT, EXPIRY)
    assert env == before


@pytest.mark.parametrize(("key", "value"), [
    ("REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED", None),
    ("REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED", "false"),
    ("REPAIR_UNVERIFIED_ACCESS_ONE_ATTEMPT_APPROVED", "TRUE"),
    ("PIPELINE_MODE", "fault"),
    ("GITHUB_WORKFLOW_REF", "attacker/repo/.github/workflows/pipeline.yml@refs/heads/main"),
    ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_REPOSITORY", "attacker/repo"),
    ("REPAIR_NO_OVERAGE_CONFIRMED", None),
    ("REPAIR_NO_OVERAGE_CONFIRMED", "false"),
    ("REPAIR_PROVIDER_TRANSMISSION_APPROVED", "false"),
    ("REPAIR_COPILOT_OWNER_ENABLED", "false"),
    ("ALERT_REPAIR_ENABLED", "false"),
    ("GITHUB_TOKEN", None),
])
def test_unverified_access_never_bypasses_other_gates(key, value):
    env = unverified_access_environment()
    if value is None:
        env.pop(key, None)
    else:
        env[key] = value
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.require_enabled(env, INCIDENT, EXPIRY)


@pytest.mark.parametrize(("incident", "expiry"), [
    ("invalid", EXPIRY),
    (INCIDENT, "invalid"),
    (INCIDENT, "2000-01-01T00:00:00+00:00"),
    (INCIDENT, "2999-01-01T00:00:00+00:00"),
])
def test_unverified_access_preserves_incident_and_expiry_checks(incident, expiry):
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.require_enabled(unverified_access_environment(), incident, expiry)


@pytest.mark.parametrize(("key", "value"), [
    ("ALERT_REPAIR_AUTHORIZED", "false"),
    ("GITHUB_RUN_ATTEMPT", "2"),
    ("ALERT_REPAIR_AUTH_RUN_ID", "5678"),
])
def test_unverified_access_still_requires_current_one_time_authorization(tmp_path, key, value):
    env = {**unverified_access_environment(), key: value}
    with pytest.raises(repair_runner.RepairGateError, match="authorization"):
        repair_runner.run_candidate(
            ROOT, INCIDENT, EXPIRY, tmp_path / "candidate.patch", environment=env,
            process_runner=lambda *_args, **_kwargs: pytest.fail("No provider call permitted"),
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REPOSITORY", "attacker/repo"),
        ("GITHUB_REF", "refs/heads/feature"),
    ],
)
def test_runner_rejects_untrusted_events_and_repositories(key, value):
    env = enabled_environment()
    env[key] = value
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.require_enabled(env, INCIDENT, EXPIRY)


def test_runner_selects_actual_coordinator_and_only_allows_narrow_tools():
    root = ROOT
    repair_runner.verify_agent_definitions(root)
    command = repair_runner.copilot_command("bounded test prompt")
    assert command[command.index("--agent") + 1] == "Prj_Coordinator"
    assert command[command.index("--prompt") + 1] == "bounded test prompt"
    assert "--allow-tool=write" in command
    assert "--allow-tool=shell(git:*)" in command
    assert "--deny-tool=shell(git push)" in command
    assert "--yolo" not in command
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.require_authorized_workflow(
            {"ALERT_REPAIR_AUTHORIZED": "false"}, INCIDENT, EXPIRY
        )


def test_workflow_is_dispatch_only_segregates_permissions_and_uses_fixed_runtime():
    workflow = yaml.load(
        (ROOT / ".github/workflows/pipeline.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert "inputs.mode == 'repair'" in workflow["jobs"]["authorization"]["if"]
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert jobs["authorization"]["permissions"] == {
        "contents": "read",
        "id-token": "write",
    }
    assert jobs["candidate"]["permissions"] == {
        "contents": "read",
        "copilot-requests": "write",
    }
    assert jobs["verify"]["permissions"] == {
        "contents": "read", "copilot-requests": "write", "id-token": "write"
    }
    assert jobs["publish-pr"]["permissions"] == {"contents": "read", "id-token": "write"}
    assert jobs["candidate"]["needs"] == "authorization"
    assert set(jobs["verify"]["needs"]) == {"authorization", "candidate"}
    assert set(jobs["publish-pr"]["needs"]) == {"authorization", "verify"}
    candidate_text = "\n".join(
        str(step) for step in jobs["candidate"]["steps"]
    )
    assert "secrets." not in candidate_text
    assert "docker build -f scripts/repair-runtime.Dockerfile" in candidate_text
    assert "ALERT_INCIDENT_ID" in candidate_text
    candidate_steps = jobs["candidate"]["steps"]
    assert not any(
        step.get("name") == "Claim receiver-accepted incident before candidate execution"
        for step in candidate_steps
    )
    assert any(
        step.get("name") == "Claim receiver-accepted incident before candidate execution"
        for step in jobs["authorization"]["steps"]
    )
    publish_step_names = [
        step.get("name") for step in jobs["publish-pr"]["steps"]
    ]
    assert publish_step_names.index(
        "Verify receiver authorization before publication credentials"
    ) < publish_step_names.index("Publish only the validated and independently tested patch")
    run_text = next(
        step["run"]
        for step in jobs["candidate"]["steps"]
        if step.get("name") == "Run existing coordinator in bounded candidate workspace"
    )
    assert "inputs.incident_id" not in run_text
    assert "$ALERT_INCIDENT_ID" in run_text
    publish_text = "\n".join(str(step) for step in jobs["publish-pr"]["steps"])
    assert "secrets.ALERT_REPAIR_PR_TOKEN" in publish_text
    assert "github.token" not in candidate_text.replace("${{ github.token }}", "")
    assert "GITHUB_TOKEN" in candidate_text


def test_candidate_patch_allows_only_save_typo_and_regression_test():
    repair_runner.validate_patch(MAIN_PATCH, TRUSTED_TEST_SOURCE)
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.validate_patch(PATCH, TRUSTED_TEST_SOURCE)


@pytest.mark.parametrize(("original", "weakened"), [
    ("assert persisted.board == board", 'assert persisted.board != PUZZLES[0]["clues"]'),
    ('assert reopened.json()["board"] == board', 'assert reopened.status_code == 200'),
    ('assert reopened.status_code == 200', 'assert True'),
    ('assert persisted.last_saved_at is None', 'assert True'),
])
def test_trusted_regression_rejects_weakened_persistence_reopen_and_rollback(original, weakened):
    assert original in TRUSTED_TEST_SOURCE
    with pytest.raises(repair_runner.RepairGateError, match="complete trusted regression"):
        repair_runner.validate_patch(
            MAIN_PATCH, TRUSTED_TEST_SOURCE.replace(original, weakened, 1)
        )


def test_candidate_patch_rejects_unrelated_executable_test_code():
    malicious_test_patch = PATCH.replace(
        b"+    assert persisted.board == board\n",
        b"+    assert persisted.board == board\n"
        b"+    __import__('os').getenv('GITHUB_TOKEN')\n",
    )
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.validate_patch(malicious_test_patch)


def test_candidate_patch_can_reuse_existing_test_without_changing_it():
    repair_runner.validate_patch(MAIN_PATCH, TRUSTED_TEST_SOURCE)


@pytest.mark.parametrize(
    "source",
    [
        "",
        f"def {repair_runner.REPAIR_TEST}():\n    pass\n",
        TRUSTED_TEST_SOURCE.replace("assert saved.status_code == 200", "assert True"),
        TRUSTED_TEST_SOURCE.replace(
            "    assert saved.status_code == 200",
            "    __import__('os').getenv('GITHUB_TOKEN')\n    assert saved.status_code == 200",
        ),
        TRUSTED_TEST_SOURCE.replace(
            f"def {repair_runner.REPAIR_TEST}", f"@arbitrary_call()\ndef {repair_runner.REPAIR_TEST}"
        ),
        TRUSTED_TEST_SOURCE + f"\ndef {repair_runner.REPAIR_TEST}():\n    pass\n",
        TRUSTED_TEST_SOURCE.replace(
            f"def {repair_runner.REPAIR_TEST}", f"async def {repair_runner.REPAIR_TEST}"
        ),
        "not valid Python!",
    ],
)
def test_candidate_patch_requires_complete_unchanged_trusted_regression(source):
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.validate_patch(MAIN_PATCH, source)


@pytest.mark.parametrize(
    "extra_code",
    [
        "__import__('os').getenv('GITHUB_TOKEN')",
        "unrelated_call()",
        "@unrelated_decorator()\ndef another_test():\n    pass",
        "import pathlib",
    ],
)
def test_candidate_patch_rejects_all_test_additions_even_with_trusted_source(extra_code):
    candidate = PATCH + b"\n" + ("\n".join("+" + line for line in extra_code.splitlines())).encode()
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.validate_patch(candidate, TRUSTED_TEST_SOURCE)


def test_candidate_test_is_rejected_before_git_application_or_publication(tmp_path, monkeypatch):
    test_path = tmp_path / "backend/tests/test_api.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(TRUSTED_TEST_SOURCE, encoding="utf-8")
    patch_path = tmp_path / "candidate.patch"
    patch_path.write_bytes(PATCH)
    monkeypatch.setattr(repair_runner.os, "environ", {
        **enabled_environment(), "ALERT_REPAIR_PR_TOKEN": "offline-only-publication-token",
    })

    def forbidden_run(*args, **kwargs):
        pytest.fail("Rejected candidate must not reach git, tests, or publication")

    monkeypatch.setattr(repair_runner.subprocess, "run", forbidden_run)
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.apply_candidate_patch(tmp_path, patch_path)
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.publish_pr(tmp_path, INCIDENT, EXPIRY, patch_path)


@pytest.mark.parametrize(
    "patch",
    [
        MAIN_PATCH + b"\ndiff --git a/README.md b/README.md\n",
        MAIN_PATCH.replace(b"body.borad", b"body.bad", 1),
        MAIN_PATCH.replace(b"body.board", b"body.bad", 1),
        PATCH.replace(
            b"+def test_deliberate",
            b"-def test_deliberate\n+def test_deliberate",
            1,
        ),
        b"GIT binary patch\n" + MAIN_PATCH,
        b"x" * (repair_runner.MAX_PATCH_BYTES + 1),
    ],
)
def test_candidate_patch_rejects_escape_noop_deletion_binary_or_oversize(patch):
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.validate_patch(patch, TRUSTED_TEST_SOURCE)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("GitHub Copilot CLI 1.0.103.\n", True),
        ("GitHub Copilot CLI 1.0.103.\nRun 'copilot update' to check for updates.\n", True),
        ("GitHub Copilot CLI 1.0.104.\nRun 'copilot update' to check for updates.\n", False),
        ("Run 'copilot update' to check for updates.\nGitHub Copilot CLI 1.0.103.\n", False),
        ("", False),
    ],
)
def test_pinned_cli_version_accepts_real_update_hint_only_for_pinned_version(output, expected):
    assert repair_runner.is_pinned_cli_version(output) is expected


def test_isolated_runtime_tmpfs_allows_cli_native_addon_but_stays_hardened(tmp_path):
    command = repair_runner.isolated_copilot_command(tmp_path, tmp_path, ["--version"])
    options = command[command.index("--tmpfs") + 1].split(":", 1)[1].split(",")
    assert "exec" in options and "noexec" not in options
    assert {"nosuid", "nodev"} <= set(options)
    assert "--read-only" in command and "--cap-drop=ALL" in command


def test_mocked_cli_boundary_uses_explicit_agent_and_never_runs_model(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "--version":
            return SimpleNamespace(
                stdout="GitHub Copilot CLI 1.0.103.\nRun 'copilot update' to check for updates.\n"
            )
        if command[0] == "docker":
            return SimpleNamespace(stdout="")
        if command[0] == "git" and "status" in command:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout=MAIN_PATCH)

    output = tmp_path / "candidate.patch"
    try:
        repair_runner.run_candidate(
            ROOT,
            INCIDENT,
            EXPIRY,
            output,
            enabled_environment(),
            process_runner=fake_run,
            executable_finder=lambda *_args, **_kwargs: "/offline/copilot",
        )
        cli_call = next(call for call in calls if "--agent" in call[0])
        assert cli_call[0][cli_call[0].index("--agent") + 1] == "Prj_Coordinator"
        assert cli_call[0][cli_call[0].index("--prompt") + 1]
        assert cli_call[1]["env"]["GITHUB_TOKEN"] == "offline-only-token"
        assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in cli_call[1]["env"]
        assert "ACTIONS_ID_TOKEN_REQUEST_URL" not in cli_call[1]["env"]
        assert all(
            "GITHUB_TOKEN" not in call[1]["env"]
            and "ACTIONS_ID_TOKEN_REQUEST_TOKEN" not in call[1]["env"]
            and "ACTIONS_ID_TOKEN_REQUEST_URL" not in call[1]["env"]
            for call in calls
            if call is not cli_call
        )
        assert output.read_bytes() == MAIN_PATCH
    finally:
        output.unlink(missing_ok=True)


def test_candidate_cannot_reach_cli_without_authorization_job_success(tmp_path):
    env = enabled_environment()
    env["ALERT_REPAIR_AUTHORIZED"] = "false"
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.run_candidate(
            ROOT,
            INCIDENT,
            EXPIRY,
            tmp_path / "candidate.patch",
            env,
            process_runner=lambda *_args, **_kwargs: pytest.fail(
                "Unclaimed incident must not reach a child process"
            ),
            executable_finder=lambda *_args, **_kwargs: pytest.fail(
                "Unclaimed incident must not probe for Copilot"
            ),
        )


def test_offline_oidc_authorization_claims_incident_and_checks_trusted_expiry():
    auth_requests = []

    class FakeResponse:
        def __init__(self, value):
            self.body = io.BytesIO(json.dumps(value).encode())
            self.status = 200
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read1(self, size):
            return self.body.read(size)

    def fake_open_url(request, timeout):
        auth_requests.append((request, timeout))
        if len(auth_requests) == 1:
            return FakeResponse({"value": "offline-signed-oidc"})
        return FakeResponse({
            "authorized": True, "expires_at": EXPIRY,
            "run_id": "1234", "run_attempt": "1", "incident_id": INCIDENT,
            "deadline": enabled_environment()["ALERT_REPAIR_DEADLINE"],
        })

    repair_runner.authorize_incident(
        enabled_environment(),
        INCIDENT,
        EXPIRY,
        action="claim",
        opener=fake_open_url,
    )
    assert len(auth_requests) == 2
    from urllib.parse import parse_qs, urlsplit

    assert parse_qs(urlsplit(auth_requests[0][0].full_url).query) == {
        "api-version": ["2.0"],
        "audience": [repair_runner.OIDC_AUDIENCE],
    }
    assert auth_requests[1][0].full_url == enabled_environment()["ALERT_REPAIR_AUTH_URL"]
    assert auth_requests[1][0].get_method() == "POST"
    assert json.loads(auth_requests[1][0].data) == {
        "incident_id": INCIDENT,
        "expires_at": EXPIRY,
        "action": "claim",
    }


def test_fake_incident_or_expiry_mismatch_fails_before_copilot_invocation():
    env = enabled_environment()
    calls = []

    class FakeResponse:
        def __init__(self, value):
            self.body = io.BytesIO(json.dumps(value).encode())
            self.status = 200
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read1(self, size):
            return self.body.read(size)

    def forged_expiry(_request, timeout):
        assert timeout == 5
        calls.append("request")
        if len(calls) == 1:
            return FakeResponse({"value": "offline-signed-oidc"})
        return FakeResponse(
            {
                "authorized": True,
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=29)
                ).isoformat(),
            }
        )

    with pytest.raises(repair_runner.RepairGateError) as error:
        repair_runner.authorize_incident(
            env, INCIDENT, EXPIRY, action="claim", opener=forged_expiry
        )
    assert calls == ["request", "request"], str(error.value)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GITHUB_RUN_ATTEMPT", "2"),  # failed/specific-job rerun inherits attempt-1 output
        ("GITHUB_RUN_ID", "5678"),
        ("GITHUB_RUN_ID", ""),
        ("GITHUB_RUN_ATTEMPT", "0"),
        ("GITHUB_RUN_ATTEMPT", "-1"),
        ("GITHUB_RUN_ATTEMPT", "01"),
        ("GITHUB_RUN_ATTEMPT", "1.0"),
        ("GITHUB_RUN_ATTEMPT", "2147483648"),
        ("ALERT_REPAIR_AUTH_RUN_ID", ""),
        ("ALERT_REPAIR_AUTH_RUN_ATTEMPT", ""),
        ("ALERT_REPAIR_AUTH_INCIDENT_ID", "b" * 64),
        ("ALERT_REPAIR_AUTH_EXPIRES_AT", "untrusted"),
    ],
)
def test_inherited_or_invalid_authorization_cannot_reinvoke_provider_or_publish(
    key, value, tmp_path, monkeypatch
):
    env = enabled_environment()
    env[key] = value
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.run_candidate(
            ROOT, INCIDENT, EXPIRY, tmp_path / "candidate.patch", env,
            process_runner=lambda *_args, **_kwargs: pytest.fail("No child process allowed"),
            executable_finder=lambda *_args, **_kwargs: pytest.fail("No CLI probe allowed"),
        )
    monkeypatch.setattr(repair_runner.os, "environ", env)
    monkeypatch.setattr(
        repair_runner.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("No git/publication allowed"),
    )
    assert repair_runner.main([
        "verify-authorization", "--incident-id", INCIDENT, "--expires-at", EXPIRY,
    ]) == 2
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.publish_pr(ROOT, INCIDENT, EXPIRY, tmp_path / "candidate.patch")


def test_workflow_binds_all_downstream_gates_to_trusted_outputs_and_attempt_artifact():
    workflow = yaml.load(
        (ROOT / ".github/workflows/pipeline.yml").read_text(), Loader=yaml.BaseLoader,
    )
    jobs = workflow["jobs"]
    assert jobs["authorization"]["outputs"] == {
        key: "${{ steps.claim.outputs." + key + " }}"
        for key in ("run_id", "run_attempt", "incident_id", "expires_at", "deadline")
    }
    for job in ("candidate", "verify", "publish-pr"):
        for step in jobs[job]["steps"]:
            env = step.get("env", {})
            if "ALERT_REPAIR_AUTHORIZED" in env:
                for suffix in ("RUN_ID", "RUN_ATTEMPT", "INCIDENT_ID", "EXPIRES_AT"):
                    assert env["ALERT_REPAIR_AUTH_" + suffix] == (
                        "${{ needs.authorization.outputs." + suffix.lower() + " }}"
                    )
            if "artifact@" in step.get("uses", ""):
                assert step["with"]["name"].endswith(
                    "${{ github.run_id }}-${{ github.run_attempt }}"
                )
        if job == "candidate":
            assert "id-token" not in jobs[job]["permissions"]
        else:
            assert jobs[job]["permissions"]["id-token"] == "write"
    steps = jobs["publish-pr"]["steps"]
    gate = next(i for i, step in enumerate(steps) if "verify-authorization" in step.get("run", ""))
    credential = next(i for i, step in enumerate(steps) if "token" in step.get("with", {}))
    assert gate < credential


class AuthResponse:
    def __init__(self, value=None, *, raw=None, status=200, content_type="application/json", length=None):
        self.body = io.BytesIO(json.dumps(value).encode() if raw is None else raw)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if length is not None:
            self.headers["Content-Length"] = length
        self.read_bytes = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read1(self, size):
        assert 0 < size <= 4096
        chunk = self.body.read(size)
        self.read_bytes += len(chunk)
        return chunk


def _trusted_authorization():
    return {
        "authorized": True, "expires_at": EXPIRY, "run_id": "1234",
        "run_attempt": "1", "incident_id": INCIDENT,
    }


@pytest.mark.parametrize("url", [
    "https://attacker.example/api/alerts/repair/claim",
    "http://simple-sudoku-backend.onrender.com/api/alerts/repair/claim",
    repair_runner.CLAIM_URL + "?redirect=evil",
    repair_runner.CLAIM_URL + "#fragment",
    repair_runner.CLAIM_URL.replace(".com/", ".com:443/"),
    repair_runner.CLAIM_URL.replace("https://", "https://user@"),
    repair_runner.CLAIM_URL.replace(".com/", ".com.evil/"),
    repair_runner.CLAIM_URL + "/",
])
def test_authorization_rejects_nonexact_endpoint_before_minting_identity(url):
    env = enabled_environment()
    env["ALERT_REPAIR_AUTH_URL"] = url
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.authorize_incident(
            env, INCIDENT, EXPIRY, action="claim",
            opener=lambda *_args, **_kwargs: pytest.fail("Must not send or mint a token"),
        )


@pytest.mark.parametrize("stage", [0, 1])
@pytest.mark.parametrize("failure", [
    "oversize", "length", "invalid-json", "array", "redirect", "error", "content-type", "timeout",
])
def test_external_authorization_responses_are_bounded_and_fail_sanitized(stage, failure):
    responses = [AuthResponse({"value": "offline-only"}), AuthResponse(_trusted_authorization())]
    invalid = {
        "oversize": AuthResponse(raw=b"x" * (repair_runner.MAX_AUTH_RESPONSE_BYTES + 100)),
        "length": AuthResponse(raw=b"", length=str(repair_runner.MAX_AUTH_RESPONSE_BYTES + 1)),
        "invalid-json": AuthResponse(raw=b"private-error-not-json"),
        "array": AuthResponse([]),
        "redirect": AuthResponse(status=302),
        "error": AuthResponse(status=500),
        "content-type": AuthResponse(content_type="text/html"),
        "timeout": TimeoutError("private-error-url-token"),
    }[failure]
    responses[stage] = invalid
    calls = []

    def fake_open(request, timeout):
        assert timeout == 5
        response = responses[len(calls)]
        calls.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    with pytest.raises(repair_runner.RepairGateError) as caught:
        repair_runner.authorize_incident(
            enabled_environment(), INCIDENT, EXPIRY, action="claim", opener=fake_open,
        )
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert len(calls) == stage + 1
    if isinstance(invalid, AuthResponse):
        assert invalid.read_bytes <= repair_runner.MAX_AUTH_RESPONSE_BYTES + 1


def test_authorization_redirect_handler_never_follows_location():
    from urllib.request import Request
    assert repair_runner._NoRedirect().redirect_request(
        Request(repair_runner.CLAIM_URL), None, 307, "redirect",
        {"Location": "https://attacker.example"}, "https://attacker.example",
    ) is None


@pytest.mark.parametrize("field,value", [
    ("run_id", "5678"), ("run_attempt", "2"), ("run_attempt", 1),
    ("incident_id", "b" * 64), ("authorized", False),
])
def test_claim_response_must_echo_current_signed_identity(field, value):
    claim = _trusted_authorization()
    claim[field] = value
    responses = iter([AuthResponse({"value": "offline"}), AuthResponse(claim)])
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.authorize_incident(
            enabled_environment(), INCIDENT, EXPIRY, action="claim",
            opener=lambda *_args, **_kwargs: next(responses),
        )


def test_authorize_writes_only_consumed_claim_outputs(tmp_path, monkeypatch):
    output = tmp_path / "job-output"
    env = {**enabled_environment(), "GITHUB_OUTPUT": str(output)}
    monkeypatch.setattr(repair_runner.os, "environ", env)
    calls = []

    def claimed(environment, incident_id, expires_at, *, action):
        calls.append(action)
        assert not output.exists()
        return {"run_id": "1234", "run_attempt": "1", "incident_id": INCIDENT, "expires_at": EXPIRY}

    monkeypatch.setattr(repair_runner, "authorize_incident", claimed)
    assert repair_runner.main(["authorize", "--incident-id", INCIDENT, "--expires-at", EXPIRY]) == 0
    assert calls == ["claim"]
    assert output.read_text().splitlines() == [
        "run_id=1234", "run_attempt=1", f"incident_id={INCIDENT}", f"expires_at={EXPIRY}",
    ]


def test_authorization_elapsed_read_deadline_rejects_trickling_response(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(repair_runner.time, "monotonic", lambda: clock[0])
    response = AuthResponse({"value": "offline"})
    read = response.read1

    def slow_read(size):
        clock[0] += repair_runner.HTTP_TIMEOUT
        return read(size)

    response.read1 = slow_read
    with pytest.raises(repair_runner.RepairGateError):
        repair_runner.authorize_incident(
            enabled_environment(), INCIDENT, EXPIRY, action="claim",
            opener=lambda *_args, **_kwargs: response,
        )
    assert response.read_bytes <= 4096
