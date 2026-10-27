"""Issue #12 delivery helper. Stdlib only; tests never contact Render.

No deploy hooks, service updates, credential creation, or automatic rollback.
API responses and exception bodies are deliberately never logged.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request


REGISTRY = "ghcr.io/sadevaraj/simple-sudoku-"
ORIGINS = {
    role: f"https://simple-sudoku-{role}.onrender.com"
    for role in ("backend", "frontend")
}
PENDING = {
    "created", "queued", "build_in_progress", "pre_deploy_in_progress",
    "update_in_progress",
}


class PipelineError(Exception):
    """Only sanitized, operator-useful messages belong here."""


def require(condition, message):
    if not condition:
        raise PipelineError(message)


def image_pair(env):
    sha = env.get("GITHUB_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha), "Invalid full commit SHA.")
    pair = {"commit": sha, "images": {}}
    for role in ORIGINS:
        digest = env.get(f"{role.upper()}_DIGEST", "")
        require(not digest or re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
                f"Invalid {role} digest.")
        pair["images"][role] = {
            "tag": f"{REGISTRY}{role}:{sha}",
            "digest": digest or None,
            "immutable": f"{REGISTRY}{role}@{digest}" if digest else None,
        }
    pair["complete"] = all(i["digest"] for i in pair["images"].values())
    return pair


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def summary(env, text):
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(text + "\n")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward a bearer credential to a redirect destination.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Render:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, path, body=None):
        request = urllib.request.Request(
            "https://api.render.com/v1" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json", "Accept": "application/json"},
            method="POST" if body is not None else "GET",
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                result = json.load(response)
                is_latest = body is None and re.fullmatch(
                    r"/services/srv-[a-z0-9]+/deploys\?limit=1", path
                )
                require(
                    isinstance(result, dict) if not is_latest
                    else isinstance(result, list) and len(result) == 1
                    and isinstance(result[0], dict),
                    "Unexpected Render API response.",
                )
                return result
        except urllib.error.HTTPError as error:
            raise PipelineError(f"Render API HTTP {error.code}; operator action required.") from None
        except (OSError, ValueError):
            raise PipelineError("Render API transport/JSON failure; inspect Render dashboard.") from None

    def health(self, url, json_health=True):
        try:
            # Separate opener: no authorization header is ever sent to the app.
            with self.opener.open(url, timeout=20) as response:
                if response.status != 200:
                    return False
                if json_health:
                    return json.load(response) == {"status": "ok"}
                return "text/html" in response.headers.get("Content-Type", "")
        except (OSError, ValueError):
            return False


def deployment_config(env):
    demo_branch = (
        env.get("GITHUB_EVENT_NAME") == "push"
        and env.get("GITHUB_REF") == "refs/heads/demo/save-recovery"
    )
    if demo_branch:
        require(env.get("DEMO_RECOVERY_ENABLED") == "true"
                and env.get("RENDER_DEV_CD_ENABLED") == "true"
                and env.get("RENDER_DEV_VERIFIED") == "true",
                "CD BLOCKED: owner-enabled repaired demo branch is required.")
        expected_tree = env.get("DEMO_EXPECTED_REPAIRED_TREE", "")
        require(re.fullmatch(r"[0-9a-f]{40}", expected_tree),
                "CD BLOCKED: exact authorized repaired tree is required.")
        try:
            actual_tree = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], check=True,
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise PipelineError("CD BLOCKED: current repaired tree could not be verified.") from None
        require(actual_tree == expected_tree,
                "CD BLOCKED: demo branch tree does not match the authorized repair.")
        from demo_control import verify_merge
        verify_merge(env, Path.cwd())
    else:
        require(env.get("RENDER_DEV_CD_ENABLED") == "true"
                and env.get("RENDER_DEV_VERIFIED") == "true",
                "CD BLOCKED: owner enablement and deployed verification flags required.")
    require(env.get("GITHUB_EVENT_NAME") == "push"
            and env.get("GITHUB_REF") in {
                "refs/heads/main", "refs/heads/demo/save-recovery"
            }
            and env.get("GITHUB_REPOSITORY") == "sadevaraj/aidevtools_prj",
            "CD BLOCKED: only this repository's authorized branch push is supported.")
    require(re.fullmatch(
        r"https://github\.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-[0-9]+",
        env.get("RENDER_DEV_VERIFICATION_URL", "")),
        "CD BLOCKED: issue #13 verification comment URL required.")
    require(bool(env.get("RENDER_API_KEY")), "CD BLOCKED: missing Render environment secret.")
    ids = {role: env.get(f"RENDER_DEV_{role.upper()}_SERVICE_ID", "") for role in ORIGINS}
    require(all(re.fullmatch(r"srv-[a-z0-9]+", value) for value in ids.values()),
            "CD BLOCKED: exact Sudoku development service IDs required.")
    require(ids["backend"] != ids["frontend"], "CD BLOCKED: service IDs must differ.")
    return ids


def demo_deployment_config(env):
    """Validate the separately owner-gated one-time fault deployment."""
    require(
        env.get("GITHUB_REPOSITORY") == "sadevaraj/aidevtools_prj"
        and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_WORKFLOW_REF")
        == "sadevaraj/aidevtools_prj/.github/workflows/development-save-demo.yml@refs/heads/main",
        "Demo deploy blocked: only the fixed owner-dispatched workflow on main is supported.",
    )
    for key in (
        "DEMO_FAULT_DEPLOY_APPROVED",
        "DEMO_ROLLBACK_PAIR_VERIFIED",
        "DEMO_WINDOW_CONFIRMED",
        "DEMO_IMAGE_PROVENANCE_VERIFIED",
        "DEMO_TARGETS_CONFIRMED",
    ):
        require(env.get(key) == "true", "Demo deploy blocked: owner prerequisite is missing.")
    evidence_url = env.get("DEMO_ROLLBACK_EVIDENCE_URL", "")
    require(re.fullmatch(
        r"https://github\.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-[0-9]+",
        evidence_url,
    ), "Demo deploy blocked: current issue #13 rollback evidence is required.")
    require(evidence_url == env.get("RENDER_DEV_VERIFICATION_URL"),
            "Demo deploy blocked: deployment and rollback evidence must match.")
    require(bool(env.get("RENDER_API_KEY")),
            "Demo deploy blocked: owner-managed Render credential is unavailable.")
    ids = {role: env.get(f"RENDER_DEV_{role.upper()}_SERVICE_ID", "") for role in ORIGINS}
    require(all(re.fullmatch(r"srv-[a-z0-9]+", value) for value in ids.values()),
            "Demo deploy blocked: exact Sudoku development service IDs are required.")
    require(ids["backend"] != ids["frontend"],
            "Demo deploy blocked: backend/frontend service IDs must differ.")
    from demo_control import validate_image_pair, validate_window
    validate_window(env.get("DEMO_EXPIRES_AT", ""))
    validate_image_pair(
        backend_digest=env.get("BACKEND_DIGEST", ""),
        frontend_digest=env.get("FRONTEND_DIGEST", ""),
        rollback_backend_digest=env.get("DEMO_ROLLBACK_BACKEND_DIGEST", ""),
        rollback_frontend_digest=env.get("DEMO_ROLLBACK_FRONTEND_DIGEST", ""),
        backend_target=ORIGINS["backend"], frontend_target=ORIGINS["frontend"],
    )
    for role in ORIGINS:
        require(re.fullmatch(r"sha256:[0-9a-f]{64}",
                             env.get(f"DEMO_ROLLBACK_{role.upper()}_DIGEST", "")),
                "Demo deploy blocked: exact healthy rollback image digests are required.")
    return ids


def deploy_demo_fault(env, report_path="demo-deployment-result.json", client=None,
                      sleep=time.sleep, clock=time.monotonic):
    """Deploy the exact owner-approved fault pair only over the verified rollback pair."""
    report = {"status": "blocked", "services": {}, "atomic": False}
    try:
        pair = image_pair(env)
        report["pair"] = pair
        require(pair["complete"], "Demo deploy blocked: both immutable image digests are required.")
        ids = demo_deployment_config(env)
        client = client or Render(env["RENDER_API_KEY"])
        preflight(client, ids)
        for role, service_id in ids.items():
            latest = client.request(f"/services/{service_id}/deploys?limit=1")
            require(isinstance(latest, list) and len(latest) == 1
                    and isinstance(latest[0], dict),
                    "Demo deploy blocked: latest deployment metadata is unavailable.")
            current = latest[0].get("deploy")
            require(isinstance(current, dict) and current.get("status") == "live"
                    and isinstance(current.get("image"), dict)
                    and current["image"].get("sha")
                    == env[f"DEMO_ROLLBACK_{role.upper()}_DIGEST"],
                    "Demo deploy blocked: currently deployed healthy rollback pair does not match.")
        require(client.health(ORIGINS["backend"] + "/api/health", True)
                and client.health(ORIGINS["frontend"] + "/", False),
                "Demo deploy blocked: current rollback services are not healthy.")
        # Reuse the established exact-digest deploy/health procedure only after
        # the distinct fault-path gates and rollback preflight succeed.
        normal_environment = {
            **env,
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "RENDER_DEV_CD_ENABLED": "true",
            "RENDER_DEV_VERIFIED": "true",
        }
        report["status"] = "delegated_to_exact_digest_deployer"
        return deploy(
            normal_environment,
            report_path=report_path,
            client=client,
            sleep=sleep,
            clock=clock,
        )
    finally:
        if report["status"] == "blocked":
            write_json(report_path, report)


def preflight(client, ids):
    # Check BOTH before mutating either. Fixed URLs allow only Sudoku development targets.
    for role, service_id in ids.items():
        service = client.request(f"/services/{service_id}")

        def check(container, key, field, expected, valid):
            # Field labels/expectations come only from code, never provider data
            # or environment values. Do not include the rejected value or body.
            prefix = f"CD BLOCKED: {role} service {field}"
            require(key in container, f"{prefix} missing; expected {expected}.")
            value = container[key]
            require(valid(value), f"{prefix} invalid; expected {expected}.")
            return value

        check(service, "id", "id", "configured service ID", lambda v: v == service_id)
        check(service, "type", "type", "web_service", lambda v: v == "web_service")
        check(service, "name", "name", f"simple-sudoku-{role}",
              lambda v: v == f"simple-sudoku-{role}")
        details = check(service, "serviceDetails", "serviceDetails", "object",
                        lambda v: isinstance(v, dict))
        check(details, "url", "serviceDetails.url", ORIGINS[role],
              lambda v: v == ORIGINS[role])
        # Preserve the existing fallback: env is used only if runtime is absent,
        # not when runtime is present but null/invalid. No new schema inference.
        runtime_key = "runtime" if "runtime" in details else "env"
        runtime_field = (f"serviceDetails.{runtime_key}" if runtime_key in details else
                         "serviceDetails.runtime (fallback serviceDetails.env)")
        check(details, runtime_key, runtime_field, "image", lambda v: v == "image")
        # Render image-backed services do not redeploy on registry tag changes.
        # After verifying image runtime, generic autoDeploy metadata is not a gate:
        # https://render.com/docs/deploying-an-image
        check(service, "imagePath", "imagePath",
              f"{REGISTRY}{role}:<tag> or {REGISTRY}{role}@sha256:<64 lowercase hex digits>",
              lambda v: isinstance(v, str) and re.fullmatch(
                  re.escape(REGISTRY + role)
                  + r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[0-9a-f]{64})", v))


def wait_live(client, service_id, deploy_id, expected_digest, sleep, clock):
    deadline = clock() + 600
    while clock() < deadline:
        result = client.request(f"/services/{service_id}/deploys/{deploy_id}")
        require(result.get("id") == deploy_id, "Render returned a different deploy ID.")
        status = result.get("status")
        if status == "live":
            require(resolved_digest(result) == expected_digest,
                    "Live deployment digest does not match the published image.")
            return
        require(isinstance(status, str) and status in PENDING,
                "Render deployment failed, canceled, or has unknown status.")
        sleep(10)
    raise PipelineError("Render deployment timed out after 600 seconds.")


def resolved_digest(result):
    image = result.get("image")
    return image.get("sha") if isinstance(image, dict) else None


def wait_health(client, url, json_health, sleep, clock):
    deadline = clock() + 120
    while clock() < deadline:
        if client.health(url, json_health):
            return
        sleep(10)
    raise PipelineError("Post-deploy health verification timed out after 120 seconds.")


def deploy(env, report_path="deployment-result.json", client=None,
           sleep=time.sleep, clock=time.monotonic):
    report = {"status": "blocked", "services": {}, "atomic": False}
    try:
        pair = image_pair(env)
        report["pair"] = pair
        require(pair["complete"], "CD BLOCKED: both published digests required.")
        ids = deployment_config(env)
        client = client or Render(env["RENDER_API_KEY"])
        preflight(client, ids)
        report["status"] = "in_progress"
        write_json(report_path, report)
        for role, service_id in ids.items():
            image = pair["images"][role]
            state = {"service_id": service_id, "status": "requesting",
                     "image": image["immutable"]}
            report["services"][role] = state
            write_json(report_path, report)
            # A POST is never retried: a transport failure may have deployed.
            result = client.request(f"/services/{service_id}/deploys",
                                    {"imageUrl": image["immutable"]})
            deploy_id = result.get("id", "")
            require(isinstance(deploy_id, str) and re.fullmatch(r"dep-[a-z0-9]+", deploy_id),
                    "Deploy response has no valid ID; inspect Render before retrying.")
            state.update(deploy_id=deploy_id, status="polling")
            write_json(report_path, report)
            wait_live(client, service_id, deploy_id, image["digest"], sleep, clock)
            state["status"] = "live_digest_verified"
            write_json(report_path, report)
            wait_health(client, ORIGINS[role] + "/api/health", True, sleep, clock)
            if role == "frontend":
                wait_health(client, ORIGINS[role] + "/", False, sleep, clock)
            state["status"] = "health_verified"
            write_json(report_path, report)
        # Recheck both identities after health checks, not just POST acceptance.
        for role, service_id in ids.items():
            state = report["services"][role]
            result = client.request(f"/services/{service_id}/deploys/{state['deploy_id']}")
            require(result.get("id") == state["deploy_id"] and result.get("status") == "live"
                    and resolved_digest(result) == pair["images"][role]["digest"],
                    "Deployment changed during verification; operator action required.")
        report["status"] = "verified"
    except PipelineError as error:
        report["status"] = "failed_or_partial" if report["services"] else "blocked"
        report["error"] = str(error)
        raise
    finally:
        write_json(report_path, report)
        summary(env, "### Render development\n```json\n"
                + json.dumps(report, indent=2) + "\n```\n"
                "Not atomic; no automatic rollback. See the deployment runbook.")
    return report


def main():
    env = os.environ
    try:
        require(len(sys.argv) == 2,
                "Usage: python3 scripts/pipeline.py record-pair|deploy|demo-deploy")
        if sys.argv[1] == "record-pair":
            pair = image_pair(env)
            write_json("image-pair.json", pair)
            summary(env, "### Published image pair\n```json\n" + json.dumps(pair, indent=2)
                    + "\n```\nCD requires BOTH owner flags, issue #13 evidence and environment setup."
                    + "\nPartial publication is not a deployable pair.")
            require(pair["complete"], "Publication incomplete; deployment blocked.")
        elif sys.argv[1] == "deploy":
            deploy(env)
        elif sys.argv[1] == "demo-deploy":
            deploy_demo_fault(env)
        else:
            raise PipelineError("Unknown pipeline command.")
    except PipelineError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
