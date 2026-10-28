"""PostgreSQL-backed alert receiver and dispatch outbox tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import io
from email.message import Message
from types import SimpleNamespace

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import delete, select

from app import alerting, main as api_module
from app.database import SessionLocal
from app.main import limiter
from app.models import AlertIncident


@pytest.fixture(autouse=True)
def clear_alert_incidents():
    limiter.reset()
    with SessionLocal.begin() as db:
        db.execute(delete(AlertIncident))
    yield
    with SessionLocal.begin() as db:
        db.execute(delete(AlertIncident))


@pytest.fixture
def configured_receiver(monkeypatch):
    monkeypatch.setattr(api_module.settings, "alert_repair_enabled", True)
    monkeypatch.setattr(api_module.settings, "app_env", "development")
    monkeypatch.setattr(
        api_module.settings, "alert_receiver_token", SecretStr("receiver-test-only")
    )
    monkeypatch.setattr(
        api_module.settings, "alert_dispatch_token", SecretStr("dispatch-test-only")
    )
    return TestClient(api_module.app, raise_server_exceptions=False)


def alert_payload(fingerprint="0123456789abcdef0123456789abcdef", **overrides):
    alert = {
        "status": "firing",
        "fingerprint": fingerprint,
        "labels": {
            "alertname": "Sudoku save HTTP 5xx",
            "service": "sudoku-api",
            "operation": "save_game",
            "severity": "warning",
        },
        "annotations": {"summary": "static metadata"},
        "values": {"A": 1},
    }
    alert.update(overrides)
    return {"status": "firing", "alerts": [alert]}


def send(client, payload, token="receiver-test-only"):
    return client.post(
        "/api/alerts/grafana",
        content=json.dumps(payload),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )


def test_receiver_is_disabled_by_default_and_does_not_exempt_normal_csrf():
    client = TestClient(api_module.app, raise_server_exceptions=False)
    disabled = send(client, alert_payload())
    assert disabled.status_code == 404
    repair_claim = client.post("/api/alerts/repair/claim", json={})
    assert repair_claim.status_code == 404
    ordinary = client.post("/api/auth/logout", json={})
    assert ordinary.status_code == 403


def test_receiver_requires_auth_and_rejects_invalid_or_oversized_payloads(configured_receiver):
    client = configured_receiver
    assert send(client, alert_payload(), token="wrong").status_code == 401
    assert send(client, {"status": "error", "alerts": []}).status_code == 422
    no_data = alert_payload()
    no_data["status"] = "no_data"
    assert send(client, no_data).status_code == 422
    assert send(
        client,
        alert_payload(status="resolved"),
    ).status_code == 422
    assert send(client, alert_payload(status="error")).status_code == 422
    assert send(client, alert_payload(status="no_data")).status_code == 422
    assert send(
        client,
        alert_payload(labels={"alertname": "Query error"}),
    ).status_code == 422
    assert send(
        client,
        alert_payload(fingerprint="not-a-fingerprint"),
    ).status_code == 422
    huge = client.post(
        "/api/alerts/grafana",
        content=b"x" * (alerting.MAX_BODY_BYTES + 1),
        headers={
            "Authorization": "Bearer receiver-test-only",
            "Content-Type": "application/json",
        },
    )
    assert huge.status_code == 413
    with SessionLocal() as db:
        assert db.scalar(select(AlertIncident.id)) is None


def test_receiver_accepts_additional_finite_numeric_expression_values(configured_receiver):
    payload = alert_payload(values={"A": 1.5, "B": 0, "threshold": 0.75})
    response = send(configured_receiver, payload)

    assert response.status_code == 202
    assert response.json() == {"accepted": True, "duplicate": False}
    with SessionLocal() as db:
        rows = db.scalars(select(AlertIncident)).all()
        assert len(rows) == 1
        assert rows[0].id != payload["alerts"][0]["fingerprint"]


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"B": 1},
        {"A": 0},
        {"A": -1},
        {"A": True},
        {"A": "1"},
        {"A": float("nan")},
        {"A": float("inf")},
        {"A": 1, "B": False},
        {"A": 1, "B": "NoData"},
        {"A": 1, "B": float("nan")},
        {"A": 1, "B": float("-inf")},
        {"A": 1, "B": {"value": 2}},
    ],
)
def test_receiver_rejects_missing_or_malformed_expression_values(
    configured_receiver, values
):
    response = send(configured_receiver, alert_payload(values=values))

    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(AlertIncident.id)) is None


def test_receiver_durably_accepts_and_deduplicates_without_storing_payload(configured_receiver):
    payload = alert_payload()
    first = send(configured_receiver, payload)
    repeated = send(configured_receiver, payload)
    assert first.status_code == repeated.status_code == 202
    assert first.json() == {"accepted": True, "duplicate": False}
    assert repeated.json() == {"accepted": True, "duplicate": True}
    with SessionLocal() as db:
        rows = db.scalars(select(AlertIncident)).all()
        assert len(rows) == 1
        incident = rows[0]
        assert incident.status == "pending"
        assert incident.attempts == 0
        assert incident.id != payload["alerts"][0]["fingerprint"]
        assert not hasattr(incident, "payload")
        assert incident.expires_at > datetime.now(timezone.utc)


def test_concurrent_replays_create_one_incident(configured_receiver):
    payload = alert_payload()

    def submit(_):
        client = TestClient(api_module.app, raise_server_exceptions=False)
        return send(client, payload).json()["duplicate"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        duplicate_flags = list(pool.map(submit, range(4)))
    assert duplicate_flags.count(False) == 1
    assert duplicate_flags.count(True) == 3
    with SessionLocal() as db:
        assert len(db.scalars(select(AlertIncident)).all()) == 1


def test_durable_global_rate_limit_rejects_overflow(configured_receiver):
    existing_payload = alert_payload()
    existing = send(configured_receiver, existing_payload)
    assert existing.status_code == 202
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        db.add_all(
            [
                AlertIncident(
                    id=f"{index:064x}",
                    status="pending",
                    attempts=0,
                    created_at=now,
                    expires_at=now + timedelta(minutes=30),
                    next_attempt_at=now,
                )
                for index in range(alerting.MAX_ACCEPTS_PER_MINUTE - 1)
            ]
        )
    response = send(configured_receiver, alert_payload("ffffffffffffffffffffffffffffffff"))
    assert response.status_code == 429
    replay = send(configured_receiver, existing_payload)
    assert replay.status_code == 202
    assert replay.json() == {"accepted": True, "duplicate": True}
    assert "receiver-test-only" not in response.text


def test_dispatch_failure_retries_are_bounded_and_safe(monkeypatch, configured_receiver, caplog):
    assert send(configured_receiver, alert_payload()).status_code == 202
    monkeypatch.setattr(
        alerting,
        "load_settings",
        lambda: SimpleNamespace(
            alert_repair_enabled=True,
            app_env="development",
            alert_dispatch_token=SecretStr("offline-dispatch-token"),
        ),
    )
    seen = []

    def failed_dispatch(incident_id, expires_at, token):
        seen.append((incident_id, expires_at, token))
        return False

    monkeypatch.setattr(alerting, "_dispatch", failed_dispatch)
    caplog.set_level(logging.WARNING)
    for attempt in range(alerting.MAX_ATTEMPTS):
        with SessionLocal.begin() as db:
            row = db.scalar(select(AlertIncident))
            if attempt:
                row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert alerting.dispatch_once()
    with SessionLocal() as db:
        incident = db.scalar(select(AlertIncident))
        assert incident.status == "failed"
        assert incident.attempts == alerting.MAX_ATTEMPTS
        assert incident.safe_error_code == "dispatch_failed"
    assert not alerting.dispatch_once()
    assert len(seen) == alerting.MAX_ATTEMPTS
    assert all(token == "offline-dispatch-token" for _, _, token in seen)
    assert all(expiry > datetime.now(timezone.utc) for _, expiry, _ in seen)
    assert "offline-dispatch-token" not in caplog.text


def test_successful_dispatch_marks_outbox_dispatched_without_logging_token(
    monkeypatch, configured_receiver, caplog
):
    assert send(configured_receiver, alert_payload()).status_code == 202
    monkeypatch.setattr(
        alerting,
        "load_settings",
        lambda: SimpleNamespace(
            alert_repair_enabled=True,
            app_env="development",
            alert_dispatch_token=SecretStr("offline-dispatch-token"),
        ),
    )
    sent = []

    def successful_dispatch(incident_id, expires_at, token):
        sent.append((incident_id, expires_at, token))
        return True

    monkeypatch.setattr(alerting, "_dispatch", successful_dispatch)
    assert alerting.dispatch_once()
    with SessionLocal() as db:
        incident = db.scalar(select(AlertIncident))
        assert incident.status == "dispatched"
        assert incident.attempts == 1
        assert incident.safe_error_code is None
    assert len(sent) == 1
    assert "offline-dispatch-token" not in caplog.text


def test_expired_incident_is_not_dispatched_and_can_be_reaccepted(configured_receiver):
    assert send(configured_receiver, alert_payload()).status_code == 202
    with SessionLocal.begin() as db:
        incident = db.scalar(select(AlertIncident))
        incident.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert alerting._claim_incident() is None
    replay = send(configured_receiver, alert_payload())
    assert replay.status_code == 202
    assert replay.json()["duplicate"] is False


def test_dispatch_failure_log_omits_exception_details(monkeypatch, configured_receiver, caplog):
    def broken_accept(*_args):
        raise RuntimeError("private-payload-and-token-marker")

    monkeypatch.setattr(api_module, "accept_incident", broken_accept)
    caplog.set_level(logging.WARNING)
    response = send(configured_receiver, alert_payload())
    assert response.status_code == 503
    assert "private-payload-and-token-marker" not in caplog.text
    assert "receiver-test-only" not in caplog.text


def test_receiver_accepts_the_configured_bearer_credential(configured_receiver):
    response = configured_receiver.post(
        "/api/alerts/grafana",
        content=json.dumps(alert_payload()),
        headers={
            "Authorization": "Bearer receiver-test-only",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "duplicate": False}


def test_dispatch_sends_configured_bearer_token_to_fixed_github_endpoint(monkeypatch):
    observed = {}

    class NoContentResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["authorization"] = request.get_header("Authorization")
        observed["timeout"] = timeout
        return NoContentResponse()

    monkeypatch.setattr(alerting.urllib.request, "urlopen", fake_urlopen)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    assert alerting._dispatch("a" * 64, expires_at, "dispatch-test-only") is True
    assert observed == {
        "url": alerting.DISPATCH_URL,
        "authorization": "Bearer dispatch-test-only",
        "timeout": 5,
    }


def _workflow_claim(
    client, incident_id, token, action="claim", expires_at=None
):
    if expires_at is None:
        with SessionLocal() as db:
            incident = db.get(AlertIncident, incident_id)
            expires_at = (
                incident.expires_at.isoformat()
                if incident is not None
                else (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
            )
    return client.post(
        "/api/alerts/repair/claim",
        json={
            "incident_id": incident_id,
            "expires_at": expires_at,
            "action": action,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


def _prepare_dispatchable_incident():
    incident_id = alerting.validate_payload(alert_payload(), development=True)
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        db.add(
            AlertIncident(
                id=incident_id,
                status="dispatched",
                attempts=1,
                created_at=now,
                expires_at=now + timedelta(minutes=20),
                next_attempt_at=now,
            )
        )
    return incident_id


def test_claim_rejects_fabricated_manual_dispatch_and_does_not_trust_future_expiry(
    configured_receiver, monkeypatch
):
    monkeypatch.setattr(
        api_module,
        "verify_github_oidc_token",
        lambda _token: alerting.WorkflowRun(run_id=1234, run_attempt=1),
    )
    response = _workflow_claim(configured_receiver, "f" * 64, "valid-run-token")
    assert response.status_code == 409
    assert response.json() == {"detail": "Incident authorization was rejected."}
    with SessionLocal() as db:
        assert db.scalar(select(AlertIncident.id)) is None


def test_manually_fabricated_future_expiry_does_not_consume_a_real_incident(
    configured_receiver, monkeypatch
):
    incident_id = _prepare_dispatchable_incident()
    monkeypatch.setattr(
        api_module,
        "verify_github_oidc_token",
        lambda _token: alerting.WorkflowRun(run_id=1234, run_attempt=1),
    )
    forged_expiry = (datetime.now(timezone.utc) + timedelta(minutes=29)).isoformat()
    response = _workflow_claim(
        configured_receiver,
        incident_id,
        "valid-run-token",
        expires_at=forged_expiry,
    )
    assert response.status_code == 409
    with SessionLocal() as db:
        incident = db.get(AlertIncident, incident_id)
        assert incident.execution_claimed_at is None


def test_claim_is_one_time_expiry_from_database_and_bound_to_run_attempt(
    configured_receiver, monkeypatch
):
    incident_id = _prepare_dispatchable_incident()
    monkeypatch.setattr(
        api_module,
        "verify_github_oidc_token",
        lambda token: alerting.WorkflowRun(
            run_id=1234 if token.startswith("run-one") else 5678,
            run_attempt=2 if token.endswith("attempt-2") else 1,
        ),
    )
    with SessionLocal() as db:
        stored_expiry = db.get(AlertIncident, incident_id).expires_at
    first = _workflow_claim(configured_receiver, incident_id, "run-one")
    assert first.status_code == 200
    assert first.json() == {
        "authorized": True,
        "expires_at": stored_expiry.isoformat(),
        "incident_id": incident_id,
        "run_id": "1234",
        "run_attempt": "1",
    }
    replay_same_run = _workflow_claim(
        configured_receiver, incident_id, "run-one", action="claim"
    )
    assert replay_same_run.status_code == 200
    verified = _workflow_claim(
        configured_receiver, incident_id, "run-one", action="verify"
    )
    assert verified.status_code == 200
    assert _workflow_claim(configured_receiver, incident_id, "run-two").status_code == 409
    assert (
        _workflow_claim(
            configured_receiver, incident_id, "run-one-attempt-2"
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        stored = db.get(AlertIncident, incident_id)
        assert stored.execution_run_id == 1234
        assert stored.execution_run_attempt == 1
        assert stored.execution_claimed_at is not None


def test_concurrent_workflow_claims_for_one_incident_have_one_winner(
    configured_receiver, monkeypatch
):
    incident_id = _prepare_dispatchable_incident()
    monkeypatch.setattr(
        api_module,
        "verify_github_oidc_token",
        lambda token: alerting.WorkflowRun(run_id=int(token), run_attempt=1),
    )

    def claim(run_id):
        client = TestClient(api_module.app, raise_server_exceptions=False)
        return _workflow_claim(client, incident_id, str(run_id)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (101, 202)))
    assert sorted(results) == [200, 409]


def test_expired_incident_and_invalid_workflow_authentication_fail_closed(
    configured_receiver, monkeypatch
):
    incident_id = _prepare_dispatchable_incident()
    with SessionLocal.begin() as db:
        db.get(AlertIncident, incident_id).expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    monkeypatch.setattr(
        api_module,
        "verify_github_oidc_token",
        lambda _token: (_ for _ in ()).throw(alerting.InvalidWorkflowIdentity()),
    )
    assert _workflow_claim(configured_receiver, incident_id, "invalid").status_code == 401
    monkeypatch.setattr(
        api_module,
        "verify_github_oidc_token",
        lambda _token: alerting.WorkflowRun(run_id=1234, run_attempt=1),
    )
    assert _workflow_claim(configured_receiver, incident_id, "expired").status_code == 409


def test_dispatch_accept_timeout_retry_creates_only_one_authorized_workflow(
    monkeypatch, configured_receiver
):
    assert send(configured_receiver, alert_payload()).status_code == 202
    monkeypatch.setattr(
        alerting,
        "load_settings",
        lambda: SimpleNamespace(
            alert_repair_enabled=True,
            app_env="development",
            alert_dispatch_token=SecretStr("offline-dispatch-token"),
        ),
    )
    dispatches = []

    def accepted_then_response_lost(incident_id, expires_at, _token):
        dispatches.append((incident_id, expires_at))
        return len(dispatches) > 1

    monkeypatch.setattr(alerting, "_dispatch", accepted_then_response_lost)
    assert alerting.dispatch_once()
    with SessionLocal.begin() as db:
        incident = db.scalar(select(AlertIncident))
        incident.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert alerting.dispatch_once()
    assert len(dispatches) == 2
    assert dispatches[0] == dispatches[1]
    monkeypatch.setattr(
        api_module,
        "verify_github_oidc_token",
        lambda token: alerting.WorkflowRun(
            run_id=7001 if token == "accepted-first-run" else 7002,
            run_attempt=1,
        ),
    )
    first = _workflow_claim(
        configured_receiver, dispatches[0][0], "accepted-first-run"
    )
    retry = _workflow_claim(configured_receiver, dispatches[1][0], "retry-run")
    assert first.status_code == 200
    assert retry.status_code == 409
    with SessionLocal() as db:
        stored = db.get(AlertIncident, dispatches[0][0])
        assert stored.attempts == 2
        assert stored.execution_run_id == 7001


def test_github_oidc_verification_requires_real_signature_and_exact_workflow(
    monkeypatch,
):
    with pytest.raises(alerting.InvalidWorkflowIdentity):
        alerting.verify_github_oidc_token("x" * 8193)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    cache, requests = _offline_jwks_cache(monkeypatch, private_key)
    monkeypatch.setattr(alerting, "_github_jwks", cache)
    now = datetime.now(timezone.utc)
    claims = {
        "iss": alerting.OIDC_ISSUER,
        "aud": alerting.OIDC_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=2)).timestamp()),
        "repository": "sadevaraj/aidevtools_prj",
        "ref": "refs/heads/main",
        "workflow_ref": alerting.OIDC_WORKFLOW_REF,
        "workflow_sha": "b" * 40,
        "event_name": "workflow_dispatch",
        "run_id": "321",
        "run_attempt": "1",
    }
    token = jwt.encode(
        claims, private_key, algorithm="RS256", headers={"kid": "offline"}
    )
    assert alerting.verify_github_oidc_token(token) == alerting.WorkflowRun(321, 1, "b" * 40)
    for key, value in (
        ("repository", "attacker/repo"),
        ("ref", "refs/heads/feature"),
        (
            "workflow_ref",
            "sadevaraj/aidevtools_prj/.github/workflows/other.yml@refs/heads/main",
        ),
        ("event_name", "push"),
        ("workflow_sha", "main"),
        ("iss", "https://attacker.example"),
        ("aud", "attacker"),
    ):
        invalid = dict(claims)
        invalid[key] = value
        signed = jwt.encode(invalid, private_key, algorithm="RS256", headers={"kid": "offline"})
        with pytest.raises(alerting.InvalidWorkflowIdentity):
            alerting.verify_github_oidc_token(signed)
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": "offline"})
    with pytest.raises(alerting.InvalidWorkflowIdentity):
        alerting.verify_github_oidc_token(forged)
    assert len(requests) == 1


class JwksResponse:
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


def _offline_jwks_cache(monkeypatch, private_key):
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    key.update(kid="offline", use="sig", alg="RS256")
    cache = alerting.GithubJwksCache()
    calls = []

    def open_jwks(request, timeout):
        assert request.full_url == alerting.OIDC_JWKS_URL
        assert timeout == alerting.JWKS_TIMEOUT_SECONDS
        assert request.get_header("Authorization") is None
        calls.append(request)
        return JwksResponse({"keys": [key]})

    monkeypatch.setattr(cache._opener, "open", open_jwks)
    return cache, calls


def test_jwks_cache_is_shared_bounded_ttl_concurrency_and_no_unknown_kid_refetch(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cache, calls = _offline_jwks_cache(monkeypatch, key)
    clock = [1000.0]
    monkeypatch.setattr(alerting.time, "monotonic", lambda: clock[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cache.get_key, ["offline"] * 8))
    assert len(calls) == 1
    assert all(result is results[0] for result in results)
    for unknown in ("missing-1", "missing-2"):
        with pytest.raises(alerting.InvalidWorkflowIdentity):
            cache.get_key(unknown)
    assert len(calls) == 1
    clock[0] += alerting.JWKS_TTL_SECONDS - 1
    cache.get_key("offline")
    assert len(calls) == 1
    clock[0] += 1
    cache.get_key("offline")
    assert len(calls) == 2
    assert len(cache._keys) <= alerting.MAX_JWKS_KEYS


@pytest.mark.parametrize("failure", [
    "oversize", "length", "too-many-keys", "empty-keys", "invalid-json", "array",
    "redirect", "error", "content-type", "timeout", "duplicate-keys", "wrong-alg",
])
def test_jwks_bounds_fail_closed_and_backoff_without_stale_keys(monkeypatch, failure):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cache, _ = _offline_jwks_cache(monkeypatch, key)
    clock = [1000.0]
    monkeypatch.setattr(alerting.time, "monotonic", lambda: clock[0])
    cache.get_key("offline")
    clock[0] += alerting.JWKS_TTL_SECONDS
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="offline")
    invalid = {
        "oversize": JwksResponse(raw=b"x" * (alerting.MAX_JWKS_BYTES + 100)),
        "length": JwksResponse(raw=b"", length=str(alerting.MAX_JWKS_BYTES + 1)),
        "too-many-keys": JwksResponse({"keys": [jwk] * (alerting.MAX_JWKS_KEYS + 1)}),
        "empty-keys": JwksResponse({"keys": []}),
        "invalid-json": JwksResponse(raw=b"private-error-not-json"),
        "array": JwksResponse([]),
        "redirect": JwksResponse(status=302),
        "error": JwksResponse(status=500),
        "content-type": JwksResponse(content_type="text/html"),
        "timeout": TimeoutError("private-error-url-token"),
        "duplicate-keys": JwksResponse({"keys": [jwk, jwk]}),
        "wrong-alg": JwksResponse({"keys": [{**jwk, "alg": "HS256"}]}),
    }[failure]
    calls = []

    def broken_fetch(request, timeout):
        calls.append(request)
        if isinstance(invalid, Exception):
            raise invalid
        return invalid

    monkeypatch.setattr(cache._opener, "open", broken_fetch)
    for _ in range(3):
        with pytest.raises(alerting.InvalidWorkflowIdentity) as caught:
            cache.get_key("offline")
        assert "private" not in str(caught.value)
    assert len(calls) == 1
    assert cache._keys == {}
    if isinstance(invalid, JwksResponse):
        assert invalid.read_bytes <= alerting.MAX_JWKS_BYTES + 1
    clock[0] += alerting.JWKS_FAILURE_COOLDOWN_SECONDS
    with pytest.raises(alerting.InvalidWorkflowIdentity):
        cache.get_key("offline")
    assert len(calls) == 2


def test_jwks_redirect_and_bad_kid_never_trigger_external_egress(monkeypatch):
    from urllib.request import Request
    assert alerting._NoJwksRedirect().redirect_request(
        Request(alerting.OIDC_JWKS_URL), None, 302, "redirect",
        {"Location": "https://attacker.example"}, "https://attacker.example",
    ) is None
    cache = alerting.GithubJwksCache()
    monkeypatch.setattr(
        cache._opener, "open",
        lambda *_args, **_kwargs: pytest.fail("Invalid kid must not fetch"),
    )
    for kid in (None, {}, "", "x" * 129, "https://attacker.example/key"):
        with pytest.raises(alerting.InvalidWorkflowIdentity):
            cache.get_key(kid)


def test_jwks_elapsed_read_deadline_rejects_trickling_response(monkeypatch):
    cache = alerting.GithubJwksCache()
    clock = [1000.0]
    monkeypatch.setattr(alerting.time, "monotonic", lambda: clock[0])
    response = JwksResponse({"keys": []})
    read = response.read1

    def slow_read(size):
        clock[0] += alerting.JWKS_TIMEOUT_SECONDS
        return read(size)

    response.read1 = slow_read
    monkeypatch.setattr(cache._opener, "open", lambda *_args, **_kwargs: response)
    with pytest.raises(alerting.InvalidWorkflowIdentity):
        cache.get_key("offline")
    assert response.read_bytes <= 4096
