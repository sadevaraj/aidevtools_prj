"""Offline delivery regression tests, also runnable with stdlib unittest."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import yaml  # Already supplied by uvicorn[standard].


ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "scripts/pipeline.py").exists():  # backend test image
    ROOT = Path("/app")
spec = importlib.util.spec_from_file_location("pipeline", ROOT / "scripts/pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

SHA = "a" * 40
DIGESTS = {"backend": "sha256:" + "b" * 64, "frontend": "sha256:" + "c" * 64}


def environment():
    return {
        "GITHUB_SHA": SHA,
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "sadevaraj/aidevtools_prj",
        "BACKEND_DIGEST": DIGESTS["backend"],
        "FRONTEND_DIGEST": DIGESTS["frontend"],
        "RENDER_DEV_CD_ENABLED": "true",
        "RENDER_DEV_VERIFIED": "true",
        "RENDER_DEV_VERIFICATION_URL":
            "https://github.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-123",
        "RENDER_API_KEY": "offline-test-only",
        "RENDER_DEV_BACKEND_SERVICE_ID": "srv-backend",
        "RENDER_DEV_FRONTEND_SERVICE_ID": "srv-frontend",
    }


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeRender:
    def __init__(self):
        self.calls = []
        self.bad_role = None
        self.status = "live"
        self.bad_digest = False
        self.healthy = True
        self.frontend_failure = False

    def request(self, path, body=None):
        self.calls.append((path, body))
        role = "backend" if "srv-backend" in path else "frontend"
        if "/deploys" not in path:
            return {
                "id": f"srv-{role}", "type": "web_service",
                "name": f"simple-sudoku-{role}", "autoDeploy": "no",
                "imagePath": f"{pipeline.REGISTRY}{role}:{SHA}",
                "serviceDetails": {
                    "runtime": "image",
                    "url": pipeline.ORIGINS[role] if role != self.bad_role else
                        "https://kanban.example.invalid",
                },
            }
        if body is not None:
            if self.frontend_failure and role == "frontend":
                raise pipeline.PipelineError("Render API HTTP 503; operator action required.")
            return {"id": f"dep-{role}"}
        return {
            "id": f"dep-{role}", "status": self.status,
            "image": {"sha": "sha256:" + "0" * 64 if self.bad_digest else DIGESTS[role]},
        }

    def health(self, url, json_health=True):
        self.calls.append((url, json_health))
        return self.healthy


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.report = Path(self.temp.name) / "report.json"
        self.env = environment()
        self.client = FakeRender()
        self.clock = Clock()

    def run_deploy(self):
        # Any accidental real HTTP request is a test failure, not a network mutation.
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden")):
            return pipeline.deploy(self.env, self.report, self.client,
                                   self.clock.sleep, self.clock)

    def assert_blocked(self):
        with self.assertRaises(pipeline.PipelineError):
            self.run_deploy()
        self.assertFalse(any(isinstance(body, dict) for _, body in self.client.calls))
        self.assertEqual(json.loads(self.report.read_text())["status"], "blocked")

    def test_exact_paired_images_and_success(self):
        result = self.run_deploy()
        self.assertEqual(result["status"], "verified")
        self.assertFalse(result["atomic"])
        posts = [(path, body) for path, body in self.client.calls if isinstance(body, dict)]
        self.assertEqual(posts, [
            (f"/services/srv-{role}/deploys",
             {"imageUrl": f"{pipeline.REGISTRY}{role}@{DIGESTS[role]}"})
            for role in ("backend", "frontend")
        ])
        self.assertIn((pipeline.ORIGINS["frontend"] + "/api/health", True), self.client.calls)
        self.assertIn((pipeline.ORIGINS["frontend"] + "/", False), self.client.calls)
        self.assertNotIn(self.env["RENDER_API_KEY"], self.report.read_text())

    def test_gates_fail_closed(self):
        for key in ("RENDER_DEV_CD_ENABLED", "RENDER_DEV_VERIFIED",
                    "RENDER_DEV_VERIFICATION_URL", "RENDER_API_KEY",
                    "RENDER_DEV_BACKEND_SERVICE_ID", "FRONTEND_DIGEST"):
            with self.subTest(key=key):
                self.env = environment()
                del self.env[key]
                self.assert_blocked()

    def test_untrusted_events_and_repository_fail_closed(self):
        for key, value in (("GITHUB_EVENT_NAME", "pull_request"),
                           ("GITHUB_EVENT_NAME", "pull_request_target"),
                           ("GITHUB_REF", "refs/heads/feature"),
                           ("GITHUB_REPOSITORY", "someone/fork")):
            with self.subTest(key=key, value=value):
                self.env = environment()
                self.env[key] = value
                self.assert_blocked()

    def test_invalid_identity_inputs(self):
        for key, value in (("GITHUB_SHA", "main"), ("GITHUB_SHA", "a" * 39),
                           ("BACKEND_DIGEST", "latest"),
                           ("FRONTEND_DIGEST", "sha256:bad"),
                           ("RENDER_DEV_FRONTEND_SERVICE_ID", "srv-backend"),
                           ("RENDER_DEV_FRONTEND_SERVICE_ID", "srv-foo/../../kanban"),
                           ("RENDER_DEV_VERIFICATION_URL", "https://example.invalid/")):
            with self.subTest(key=key):
                self.env = environment()
                self.env[key] = value
                self.assert_blocked()

    def test_both_services_checked_before_first_deploy(self):
        self.client.bad_role = "frontend"
        self.assert_blocked()
        self.assertEqual(len(self.client.calls), 2)

    def test_service_identity_and_image_rejected(self):
        for field, value in (("name", "kanban-backend"), ("type", "private_service"),
                             ("id", "srv-wrong"),
                             ("imagePath", "ghcr.io/other/kanban:latest")):
            with self.subTest(field=field):
                self.client = FakeRender()
                original = self.client.request
                def changed(path, body=None):
                    result = original(path, body)
                    result[field] = value
                    return result
                self.client.request = changed
                self.assert_blocked()

    def assert_preflight_diagnostic(self, role, field, expected, value=None, missing=False,
                                    auto_deploy="no"):
        self.client = FakeRender()
        original = self.client.request

        def changed(path, body=None):
            result = original(path, body)
            if "/deploys" not in path:
                if auto_deploy is None:
                    del result["autoDeploy"]
                else:
                    result["autoDeploy"] = auto_deploy
            if path == f"/services/srv-{role}":
                container = result
                keys = field.split(".")
                for key in keys[:-1]:
                    container = container[key]
                if missing:
                    del container[keys[-1]]
                else:
                    container[keys[-1]] = value
                # Unrelated metadata must never enter diagnostic output.
                result["untrusted"] = "metadata-secret-marker"
            return result

        self.client.request = changed
        self.env["GITHUB_STEP_SUMMARY"] = str(Path(self.temp.name) / "summary")
        with self.assertRaises(pipeline.PipelineError) as error:
            self.run_deploy()
        self.assertEqual(str(error.exception), expected)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["services"], {})
        self.assertEqual(report["error"], expected)
        self.assertEqual(self.client.calls, [
            (f"/services/srv-{name}", None)
            for name in (("backend",) if role == "backend" else ("backend", "frontend"))
        ])
        for text in (str(error.exception), self.report.read_text(),
                     Path(self.env["GITHUB_STEP_SUMMARY"]).read_text()):
            self.assertNotIn("metadata-secret-marker", text)
            self.assertNotIn("untrusted-value-marker", text)
            self.assertNotIn(self.env["RENDER_API_KEY"], text)

    def test_preflight_each_field_missing_or_invalid_is_safe_and_never_posts(self):
        for role in ("backend", "frontend"):
            fields = {
                "id": "configured service ID",
                "type": "web_service",
                "name": f"simple-sudoku-{role}",
                "serviceDetails": "object",
                "serviceDetails.url": pipeline.ORIGINS[role],
                "serviceDetails.runtime": "image",
                "imagePath": f"{pipeline.REGISTRY}{role}:<tag> or "
                             f"{pipeline.REGISTRY}{role}@sha256:<64 lowercase hex digits>",
            }
            for field, expectation in fields.items():
                for missing, value in (
                    (True, None), (False, None), (False, ""),
                    (False, "untrusted-value-marker\nBearer offline-test-only"),
                    (False, ["untrusted-value-marker"]),
                ):
                    with self.subTest(role=role, field=field, missing=missing, value=value):
                        diagnostic_field = field
                        if field == "serviceDetails.runtime" and missing:
                            diagnostic_field += " (fallback serviceDetails.env)"
                        expected = (
                            f"CD BLOCKED: {role} service {diagnostic_field} "
                            f"{'missing' if missing else 'invalid'}; expected {expectation}."
                        )
                        for auto_deploy in (None, "yes", "no"):
                            with self.subTest(auto_deploy=auto_deploy):
                                self.assert_preflight_diagnostic(
                                    role, field, expected, value, missing, auto_deploy)

    def test_preflight_runtime_fallback_and_precedence_unchanged(self):
        for role in ("backend", "frontend"):
            for runtime_present, runtime, env in (
                (False, None, "image"), (True, "image", "docker"),
                (False, None, "docker"), (False, None, None),
                (True, None, "image"), (True, "docker", "image"),
            ):
                with self.subTest(role=role, runtime_present=runtime_present,
                                  runtime=runtime, env=env):
                    self.client = FakeRender()
                    original = self.client.request

                    def changed(path, body=None):
                        result = original(path, body)
                        if path == f"/services/srv-{role}":
                            details = result["serviceDetails"]
                            details["env"] = env
                            if runtime_present:
                                details["runtime"] = runtime
                            else:
                                del details["runtime"]
                        return result

                    self.client.request = changed
                    if (runtime if runtime_present else env) == "image":
                        self.assertEqual(self.run_deploy()["status"], "verified")
                    else:
                        key = "runtime" if runtime_present else "env"
                        expected = (f"CD BLOCKED: {role} service serviceDetails.{key} "
                                    "invalid; expected image.")
                        with self.assertRaises(pipeline.PipelineError) as error:
                            self.run_deploy()
                        self.assertEqual(str(error.exception), expected)
                        self.assertFalse(any(isinstance(body, dict)
                                             for _, body in self.client.calls))

    def test_preflight_image_checks_remain_strict(self):
        for role in ("backend", "frontend"):
            for field, expectation, values in (
                ("imagePath", f"{pipeline.REGISTRY}{role}:<tag> or "
                              f"{pipeline.REGISTRY}{role}@sha256:<64 lowercase hex digits>",
                 (f"{pipeline.REGISTRY}{role}", f"{pipeline.REGISTRY}{role}:",
                  f"{pipeline.REGISTRY}{role}:tag/extra",
                  f"{pipeline.REGISTRY}{role}@sha256:bad",
                  f"{pipeline.REGISTRY}{role}-other:tag")),
            ):
                for value in values:
                    with self.subTest(role=role, field=field, value=value):
                        self.assert_preflight_diagnostic(
                            role, field,
                            f"CD BLOCKED: {role} service {field} invalid; expected {expectation}.",
                            value)

    def test_generic_autodeploy_metadata_is_not_an_image_runtime_gate(self):
        # None here means the generic field is absent. Exercise both services
        # independently, including mixed metadata, and the complete deploy flow.
        for backend in (None, "yes", "no"):
            for frontend in (None, "yes", "no"):
                with self.subTest(backend=backend, frontend=frontend):
                    self.client = FakeRender()
                    original = self.client.request

                    def changed(path, body=None):
                        result = original(path, body)
                        if "/deploys" not in path:
                            value = backend if "srv-backend" in path else frontend
                            if value is None:
                                del result["autoDeploy"]
                            else:
                                result["autoDeploy"] = value
                        return result

                    self.client.request = changed
                    self.assertEqual(self.run_deploy()["status"], "verified")
                    self.assertEqual(self.client.calls[:2], [
                        (f"/services/srv-{role}", None) for role in ("backend", "frontend")
                    ])
                    self.assertEqual(
                        [(path, body) for path, body in self.client.calls
                         if isinstance(body, dict)],
                        [(f"/services/srv-{role}/deploys",
                          {"imageUrl": f"{pipeline.REGISTRY}{role}@{DIGESTS[role]}"})
                         for role in ("backend", "frontend")])

    def test_runtime_still_blocks_before_any_post_with_generic_autodeploy_metadata(self):
        for role in ("backend", "frontend"):
            for auto_deploy in (None, "yes", "no"):
                for runtime in ({}, {"runtime": "docker"}, {"runtime": None},
                                {"runtime": []}, {"runtime": "invalid"},
                                {"runtime": None, "env": "image"}, {"env": "docker"}):
                    with self.subTest(role=role, auto_deploy=auto_deploy, runtime=runtime):
                        self.client = FakeRender()
                        original = self.client.request

                        def changed(path, body=None):
                            result = original(path, body)
                            if "/deploys" not in path:
                                if auto_deploy is None:
                                    del result["autoDeploy"]
                                else:
                                    result["autoDeploy"] = auto_deploy
                                if path == f"/services/srv-{role}":
                                    result["serviceDetails"].pop("runtime")
                                    result["serviceDetails"].update(runtime)
                            return result

                        self.client.request = changed
                        self.assert_blocked()
                        self.assertEqual(json.loads(self.report.read_text())["services"], {})
                        self.assertEqual(self.client.calls, [
                            (f"/services/srv-{name}", None) for name in
                            (("backend",) if role == "backend" else ("backend", "frontend"))
                        ])

    def test_preflight_accepts_existing_tag_and_digest_image_formats(self):
        for suffix in (":release_1.2-3", "@sha256:" + "d" * 64):
            with self.subTest(suffix=suffix):
                self.client = FakeRender()
                original = self.client.request

                def changed(path, body=None):
                    result = original(path, body)
                    if "/deploys" not in path:
                        role = "backend" if "srv-backend" in path else "frontend"
                        result["imagePath"] = f"{pipeline.REGISTRY}{role}{suffix}"
                    return result

                self.client.request = changed
                self.assertEqual(self.run_deploy()["status"], "verified")

    def test_preflight_cli_diagnostic_redacts_runtime_metadata(self):
        original = self.client.request

        def changed(path, body=None):
            result = original(path, body)
            result["serviceDetails"]["runtime"] = {
                "credential": "untrusted-value-marker\nBearer offline-test-only"
            }
            return result

        self.client.request = changed
        stdout, stderr = io.StringIO(), io.StringIO()
        real_deploy = pipeline.deploy
        with patch.dict("os.environ", self.env, clear=True), \
                patch("sys.argv", ["pipeline.py", "deploy"]), \
                patch.object(pipeline, "deploy", side_effect=lambda env: real_deploy(
                    env, self.report, self.client, self.clock.sleep, self.clock)), \
                patch("urllib.request.OpenerDirector.open",
                      side_effect=AssertionError("network forbidden")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(pipeline.main(), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(),
                         "CD BLOCKED: backend service serviceDetails.runtime invalid; "
                         "expected image.\n")
        self.assertNotIn("untrusted-value-marker", self.report.read_text())
        self.assertFalse(any(isinstance(body, dict) for _, body in self.client.calls))

    def test_pending_then_live(self):
        original = self.client.request
        pending = [True]
        def transition(path, body=None):
            result = original(path, body)
            if "/deploys/dep-" in path and pending:
                pending.pop()
                result["status"] = "queued"
            return result
        self.client.request = transition
        self.assertEqual(self.run_deploy()["status"], "verified")
        self.assertEqual(self.clock.now, 10)

    def test_invalid_deploy_id_is_not_retried(self):
        original = self.client.request
        def invalid_id(path, body=None):
            result = original(path, body)
            if body is not None:
                result["id"] = "../other-service"
            return result
        self.client.request = invalid_id
        with self.assertRaisesRegex(pipeline.PipelineError, "valid ID"):
            self.run_deploy()
        self.assertEqual(sum(isinstance(body, dict) for _, body in self.client.calls), 1)

    def test_malformed_provider_metadata_fails_closed(self):
        original = self.client.request
        def malformed(path, body=None):
            result = original(path, body)
            result["serviceDetails"] = None
            return result
        self.client.request = malformed
        self.assert_blocked()

    def test_malformed_provider_deploy_fails_explicitly(self):
        original = self.client.request
        def malformed(path, body=None):
            result = original(path, body)
            if "/deploys/dep-" in path:
                result["image"] = None
            return result
        self.client.request = malformed
        with self.assertRaisesRegex(pipeline.PipelineError, "digest"):
            self.run_deploy()

    def test_digest_change_after_health_fails(self):
        original_health = self.client.health
        def changed(url, json_health=True):
            if url == pipeline.ORIGINS["frontend"] + "/":
                self.client.bad_digest = True
            return original_health(url, json_health)
        self.client.health = changed
        with self.assertRaisesRegex(pipeline.PipelineError, "changed"):
            self.run_deploy()

    def test_cli_partial_publication_writes_artifact_and_fails(self):
        env = environment()
        env["FRONTEND_DIGEST"] = ""
        with patch.dict("os.environ", env, clear=True), \
                patch("sys.argv", ["pipeline.py", "record-pair"]), \
                patch.object(pipeline, "write_json") as write:
            self.assertEqual(pipeline.main(), 1)
        self.assertEqual(write.call_args.args[0], "image-pair.json")
        self.assertFalse(write.call_args.args[1]["complete"])

    def test_failed_or_unknown_status_never_deploys_frontend(self):
        for status in ("build_failed", "pre_deploy_failed", "update_failed",
                       "canceled", "deactivated", "surprise"):
            with self.subTest(status=status):
                self.client = FakeRender()
                self.client.status = status
                with self.assertRaises(pipeline.PipelineError):
                    self.run_deploy()
                self.assertNotIn("frontend", json.loads(self.report.read_text())["services"])

    def test_digest_mismatch_fails(self):
        self.client.bad_digest = True
        with self.assertRaisesRegex(pipeline.PipelineError, "digest"):
            self.run_deploy()

    def test_bounded_poll_timeout(self):
        self.client.status = "update_in_progress"
        with self.assertRaisesRegex(pipeline.PipelineError, "600 seconds"):
            self.run_deploy()
        self.assertEqual(self.clock.now, 600)

    def test_bounded_health_timeout(self):
        self.client.healthy = False
        with self.assertRaisesRegex(pipeline.PipelineError, "health"):
            self.run_deploy()
        self.assertEqual(self.clock.now, 120)

    def test_partial_pair_is_recorded_and_post_is_not_retried(self):
        self.client.frontend_failure = True
        with self.assertRaises(pipeline.PipelineError):
            self.run_deploy()
        report = json.loads(self.report.read_text())
        self.assertEqual(report["status"], "failed_or_partial")
        self.assertEqual(report["services"]["backend"]["status"], "health_verified")
        self.assertEqual(report["services"]["frontend"]["status"], "requesting")
        self.assertEqual(sum(body is not None and isinstance(body, dict)
                             for _, body in self.client.calls), 2)

    def test_partial_publication_has_no_deployable_pair(self):
        self.env["FRONTEND_DIGEST"] = ""
        pair = pipeline.image_pair(self.env)
        self.assertFalse(pair["complete"])
        self.assertIsNone(pair["images"]["frontend"]["immutable"])
        self.assert_blocked()

    def test_api_errors_sanitized_without_response_body(self):
        client = pipeline.Render("secret-never-in-logs")
        with patch.object(client.opener, "open", side_effect=urllib.error.HTTPError(
                "https://api.render.com", 401, "sensitive body", {}, None)):
            with self.assertRaises(pipeline.PipelineError) as error:
                client.request("/services/srv-backend")
        self.assertIn("401", str(error.exception))
        self.assertNotIn("sensitive", str(error.exception))
        self.assertNotIn("secret", str(error.exception))

    def test_redirect_is_never_followed(self):
        self.assertIsNone(pipeline.NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://example.invalid"))

    def test_summary_is_useful_and_secret_free(self):
        self.env["GITHUB_STEP_SUMMARY"] = str(Path(self.temp.name) / "summary")
        self.run_deploy()
        text = Path(self.env["GITHUB_STEP_SUMMARY"]).read_text()
        self.assertIn(DIGESTS["frontend"], text)
        self.assertIn("Not atomic", text)
        self.assertNotIn(self.env["RENDER_API_KEY"], text)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / ".github/workflows/pipeline.yml"
        cls.workflow = yaml.load(cls.path.read_text(), Loader=yaml.BaseLoader)

    def test_triggers_and_read_only_default(self):
        self.assertEqual(set(self.workflow["on"]), {"pull_request", "push"})
        self.assertEqual(self.workflow["on"]["push"]["branches"], ["main"])
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")

    def test_required_root_suite_and_publication_gate(self):
        jobs = self.workflow["jobs"]
        self.assertIn("sh scripts/test.sh", [s.get("run") for s in jobs["tests"]["steps"]])
        self.assertEqual(jobs["publish"]["needs"], "tests")
        for job in ("publish", "deploy-development"):
            self.assertIn("github.event_name == 'push'", jobs[job]["if"])
            self.assertIn("github.ref == 'refs/heads/main'", jobs[job]["if"])
            self.assertIn("github.repository == 'sadevaraj/aidevtools_prj'", jobs[job]["if"])
        self.assertEqual(jobs["publish"]["permissions"],
                         {"contents": "read", "packages": "write"})
        self.assertEqual(jobs["deploy-development"]["permissions"], {"contents": "read"})
        self.assertEqual(jobs["deploy-development"]["needs"], ["tests", "publish"])

    def test_exact_publication_and_environment_only_deploy_secret(self):
        jobs = self.workflow["jobs"]
        deploy = jobs["deploy-development"]
        self.assertEqual(deploy["environment"], "sudoku-development")
        for flag in ("RENDER_DEV_CD_ENABLED", "RENDER_DEV_VERIFIED"):
            self.assertIn(f"vars.{flag} == 'true'", deploy["if"])
        login = next(s for s in jobs["publish"]["steps"]
                     if s.get("uses", "").startswith("docker/login-action@"))
        self.assertEqual(login["with"]["password"], "${{ secrets.GITHUB_TOKEN }}")
        for role in ("backend", "frontend"):
            build = next(s for s in jobs["publish"]["steps"] if s.get("id") == role)
            self.assertEqual(build["with"]["tags"],
                             f"{pipeline.REGISTRY}{role}:${{{{ github.sha }}}}")
            self.assertEqual(build["with"]["push"], "true")
        self.assertNotIn("RENDER_API_KEY", json.dumps(jobs["tests"]))
        self.assertNotIn("RENDER_API_KEY", json.dumps(jobs["publish"]))

    def test_pinned_actions_and_failure_artifacts(self):
        for job in self.workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"^[^@]+@[0-9a-f]{40}$")
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertEqual(step["with"]["persist-credentials"], "false")
                if step.get("uses", "").startswith("actions/upload-artifact@"):
                    self.assertEqual(step["if"], "always()")
                    self.assertEqual(step["with"]["if-no-files-found"], "error")


if __name__ == "__main__":
    unittest.main()
