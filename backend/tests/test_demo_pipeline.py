"""Offline development fault deployment and verified rollback pair preflights."""

from datetime import datetime, timedelta, timezone
import sys

import pytest

from test_pipeline import pipeline, environment, FakeRender, Clock, DIGESTS, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def demo_environment():
    return {
        **environment(),
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF":
            "sadevaraj/aidevtools_prj/.github/workflows/pipeline.yml@refs/heads/main",
        "PIPELINE_MODE": "fault",
        "DEMO_FAULT_DEPLOY_APPROVED": "true", "DEMO_ROLLBACK_PAIR_VERIFIED": "true",
        "DEMO_WINDOW_CONFIRMED": "true", "DEMO_IMAGE_PROVENANCE_VERIFIED": "true",
        "DEMO_TARGETS_CONFIRMED": "true",
        "DEMO_ROLLBACK_EVIDENCE_URL": environment()["RENDER_DEV_VERIFICATION_URL"],
        "DEMO_ROLLBACK_BACKEND_DIGEST": "sha256:" + "1" * 64,
        "DEMO_ROLLBACK_FRONTEND_DIGEST": "sha256:" + "2" * 64,
        "DEMO_EXPIRES_AT": (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat(),
    }


class DemoRender(FakeRender):
    def __init__(self):
        super().__init__()
        self.rollback = {"backend": "sha256:" + "1" * 64, "frontend": "sha256:" + "2" * 64}
        self.rollback_status = "live"

    def request(self, path, body=None):
        if path.endswith("/deploys?limit=1"):
            self.calls.append((path, body))
            role = "backend" if "srv-backend" in path else "frontend"
            return [{"deploy": {"status": self.rollback_status, "image": {"sha": self.rollback[role]}}}]
        return super().request(path, body)


def test_fault_deployment_requires_actual_healthy_rollback_and_pins_exact_pair(tmp_path):
    env = demo_environment()
    provider = DemoRender()
    clock = Clock()
    pipeline.deploy_demo_fault(
        env, str(tmp_path / "report.json"), client=provider, sleep=clock.sleep, clock=clock,
    )
    posts = [(path, body) for path, body in provider.calls if isinstance(body, dict)]
    assert len(posts) == 2
    assert posts[0][1]["imageUrl"] == pipeline.REGISTRY + "backend@" + DIGESTS["backend"]
    assert posts[1][1]["imageUrl"] == pipeline.REGISTRY + "frontend@" + DIGESTS["frontend"]


@pytest.mark.parametrize("change", ["wrong-backend", "wrong-frontend", "queued", "unhealthy", "wrong-target"])
def test_wrong_or_unverified_rollback_stops_before_any_deployment_post(tmp_path, change):
    provider = DemoRender()
    if change == "wrong-backend":
        provider.rollback["backend"] = "sha256:" + "0" * 64
    elif change == "wrong-frontend":
        provider.rollback["frontend"] = "sha256:" + "0" * 64
    elif change == "queued":
        provider.rollback_status = "build_in_progress"
    elif change == "unhealthy":
        provider.healthy = False
    else:
        provider.bad_role = "frontend"
    with pytest.raises(pipeline.PipelineError):
        pipeline.deploy_demo_fault(demo_environment(), str(tmp_path / "report.json"), client=provider)
    assert not any(isinstance(body, dict) for _, body in provider.calls)


@pytest.mark.parametrize("key,value", [
    ("DEMO_FAULT_DEPLOY_APPROVED", ""), ("DEMO_WINDOW_CONFIRMED", "false"),
    ("DEMO_ROLLBACK_EVIDENCE_URL", "https://attacker.invalid"),
    ("GITHUB_REF", "refs/heads/feature"),
    ("PIPELINE_MODE", "repair"),
    ("GITHUB_WORKFLOW_REF", "other"), ("RENDER_API_KEY", ""),
])
def test_missing_owner_or_workflow_gates_prevent_provider_access(tmp_path, key, value):
    provider = DemoRender()
    with pytest.raises(pipeline.PipelineError):
        pipeline.deploy_demo_fault(
            {**demo_environment(), key: value}, str(tmp_path / "report.json"), client=provider,
        )
    assert provider.calls == []
