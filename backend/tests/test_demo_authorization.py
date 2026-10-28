"""Durable owner-gated development-demo authorization tests."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app import main as api_module
from app.alerting import WorkflowRun, authorize_incident, IncidentAuthorizationError
from app.database import SessionLocal
from app.models import AlertIncident, DevelopmentDemoAuthorization


@pytest.fixture(autouse=True)
def clear_demo_authorizations():
    with SessionLocal.begin() as db:
        db.execute(
            update(DevelopmentDemoAuthorization)
            .where(DevelopmentDemoAuthorization.alert_incident_id.is_not(None))
            .values(alert_incident_id=None)
        )
        db.execute(delete(AlertIncident))
        db.execute(delete(DevelopmentDemoAuthorization))
    yield
    with SessionLocal.begin() as db:
        db.execute(
            update(DevelopmentDemoAuthorization)
            .where(DevelopmentDemoAuthorization.alert_incident_id.is_not(None))
            .values(alert_incident_id=None)
        )
        db.execute(delete(AlertIncident))
        db.execute(delete(DevelopmentDemoAuthorization))


@pytest.fixture
def enabled_demo(monkeypatch):
    settings = api_module.settings
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "alert_repair_enabled", True)
    monkeypatch.setattr(settings, "demo_control_enabled", True)
    monkeypatch.setattr(settings, "demo_control_token", SecretStr("demo-owner-only-test"))
    monkeypatch.setattr(settings, "alert_receiver_token", SecretStr("grafana-test-only"))
    monkeypatch.setattr(settings, "alert_dispatch_token", SecretStr("dispatch-test-only"))
    api_module.limiter.reset()
    return TestClient(api_module.app, raise_server_exceptions=False)


def arm_body(**overrides):
    expires = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    body = {
        "trusted_revision": "a" * 40,
        "fault_revision": "b" * 40,
        "expected_repaired_tree": "c" * 40,
        "branch": "main",
        "backend_digest": "sha256:" + "1" * 64,
        "frontend_digest": "sha256:" + "2" * 64,
        "rollback_backend_digest": "sha256:" + "3" * 64,
        "rollback_frontend_digest": "sha256:" + "4" * 64,
        "expires_at": expires,
        "rollback_evidence_url":
            "https://github.com/sadevaraj/aidevtools_prj/issues/13#issuecomment-999999",
        "rollback_pair_verified": True,
        "development_window_confirmed": True,
        "image_provenance_verified": True,
    }
    return {**body, **overrides}


def alert_payload():
    return {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "0123456789abcdef0123456789abcdef",
                "labels": {
                    "alertname": "Sudoku save HTTP 5xx",
                    "service": "sudoku-api",
                    "operation": "save_game",
                    "severity": "warning",
                },
                "values": {"A": 1},
            }
        ],
    }


def test_demo_arm_rejects_missing_auth_disabled_and_malformed_owner_inputs(
    enabled_demo, monkeypatch
):
    client = enabled_demo
    payload = arm_body()
    assert client.post("/api/alerts/demo/arm", json=payload).status_code == 401
    headers = {"Authorization": "Bearer demo-owner-only-test"}
    for changed in (
        {"branch": "feature"},
        {"trusted_revision": "not-a-full-revision"},
        {"backend_digest": "mutable:tag"},
        {"rollback_backend_digest": "sha256:" + "1" * 64},
        {"backend_target": "https://kanban.invalid"},
        {"development_window_confirmed": "true"},
        {"rollback_pair_verified": False},
        {"rollback_evidence_url": "https://attacker.invalid/"},
    ):
        api_module.limiter.reset()
        response = client.post(
            "/api/alerts/demo/arm", json={**payload, **changed}, headers=headers
        )
        assert response.status_code == 422
    monkeypatch.setattr(api_module.settings, "demo_control_enabled", False)
    api_module.limiter.reset()
    assert client.post(
        "/api/alerts/demo/arm", json=payload, headers=headers
    ).status_code == 404


def test_demo_arm_binds_alert_to_fixed_server_authorization_and_rejects_second_arm(
    enabled_demo,
):
    client = enabled_demo
    headers = {"Authorization": "Bearer demo-owner-only-test"}
    armed = client.post("/api/alerts/demo/arm", json=arm_body(), headers=headers)
    assert armed.status_code == 201
    assert armed.json()["branch"] == "main"
    assert armed.json()["trusted_revision"] == "a" * 40
    assert client.post(
        "/api/alerts/demo/arm", json=arm_body(), headers=headers
    ).status_code == 409

    response = client.post(
        "/api/alerts/grafana",
        content=json.dumps(alert_payload()),
        headers={
            "Authorization": "Bearer grafana-test-only",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 202
    with SessionLocal() as db:
        incident = db.scalar(select(AlertIncident))
        demo = db.get(DevelopmentDemoAuthorization, incident.demo_authorization_id)
        assert incident.demo_authorization_id == armed.json().get("authorization_id", demo.id)
        assert demo.alert_incident_id == incident.id
        assert demo.state == "claimed"
        assert demo.trusted_revision == "a" * 40
        assert demo.fault_revision == "b" * 40
        assert demo.expected_repaired_tree == "c" * 40
        assert demo.branch == "main"
        assert demo.backend_target == "https://simple-sudoku-backend.onrender.com"
        assert demo.frontend_target == "https://simple-sudoku-frontend.onrender.com"
        assert not hasattr(demo, "commands")
        incident_id = incident.id
        incident_expiry = incident.expires_at.isoformat()

    with SessionLocal.begin() as db:
        db.get(AlertIncident, incident_id).status = "dispatched"
        db.get(AlertIncident, incident_id).attempts = 1
    with SessionLocal.begin() as db:
        authorize_incident(
            db,
            incident_id,
            WorkflowRun(12345, 1, "b" * 40),
            expected_expires_at=incident_expiry,
            claim=True,
            require_demo_authorization=True,
        )
    with SessionLocal.begin() as db:
        authorize_incident(
            db,
            incident_id,
            WorkflowRun(12345, 1, "b" * 40),
            expected_expires_at=incident_expiry,
            claim=False,
            require_demo_authorization=True,
        )
    with SessionLocal.begin() as db:
        from app.alerting import IncidentAuthorizationError

        with pytest.raises(IncidentAuthorizationError):
            authorize_incident(
                db,
                incident_id,
                WorkflowRun(12346, 1, "b" * 40),
                expected_expires_at=incident_expiry,
                claim=True,
                require_demo_authorization=True,
            )


def test_demo_receiver_fails_closed_without_owner_armed_authorization(enabled_demo):
    response = enabled_demo.post(
        "/api/alerts/grafana",
        content=json.dumps(alert_payload()),
        headers={
            "Authorization": "Bearer grafana-test-only",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(AlertIncident.id)) is None


OWNER_HEADERS = {"Authorization": "Bearer demo-owner-only-test"}
GRAFANA_HEADERS = {
    "Authorization": "Bearer grafana-test-only", "Content-Type": "application/json",
}


def accepted_demo(client):
    armed = client.post("/api/alerts/demo/arm", json=arm_body(), headers=OWNER_HEADERS)
    assert armed.status_code == 201
    assert client.post(
        "/api/alerts/grafana", content=json.dumps(alert_payload()), headers=GRAFANA_HEADERS
    ).status_code == 202
    with SessionLocal.begin() as db:
        incident = db.scalar(select(AlertIncident))
        incident.attempts = 1
        incident.status = "dispatched"
        return incident.id, incident.expires_at.isoformat()


@pytest.mark.parametrize("expiry", [
    "invalid", "2020-01-01T00:00:00Z", "2999-01-01T00:00:00Z", "2026-10-28T00:00:00",
])
def test_arm_rejects_bad_expired_naive_and_unbounded_ttl(enabled_demo, expiry):
    assert enabled_demo.post(
        "/api/alerts/demo/arm", json=arm_body(expires_at=expiry), headers=OWNER_HEADERS,
    ).status_code == 422


def test_demo_is_disabled_in_production_and_requires_separate_owner_credential(enabled_demo, monkeypatch):
    monkeypatch.setattr(api_module.settings, "app_env", "production")
    assert enabled_demo.post(
        "/api/alerts/demo/arm", json=arm_body(), headers=OWNER_HEADERS
    ).status_code == 404
    monkeypatch.setattr(api_module.settings, "app_env", "development")
    monkeypatch.setattr(api_module.settings, "demo_control_token", None)
    assert enabled_demo.post(
        "/api/alerts/demo/arm", json=arm_body(), headers=OWNER_HEADERS
    ).status_code == 503


def test_parallel_owner_arms_are_serialized_by_postgres(enabled_demo):
    payload = arm_body()
    def arm(_):
        return enabled_demo.post(
            "/api/alerts/demo/arm", json=payload, headers=OWNER_HEADERS,
        ).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(arm, range(2))) == [201, 409]
    with SessionLocal() as db:
        assert len(db.scalars(select(DevelopmentDemoAuthorization)).all()) == 1


def test_parallel_claims_accept_one_run_and_reject_reruns(enabled_demo):
    incident_id, expiry = accepted_demo(enabled_demo)
    def claim(run_id):
        try:
            with SessionLocal.begin() as db:
                authorize_incident(
                    db, incident_id, WorkflowRun(run_id, 1, "b" * 40),
                    expected_expires_at=expiry, claim=True, require_demo_authorization=True,
                )
            return True
        except IncidentAuthorizationError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, (777, 778))) == [False, True]
    with SessionLocal() as db:
        incident = db.get(AlertIncident, incident_id)
        run = incident.execution_run_id
        demo = db.get(DevelopmentDemoAuthorization, incident.demo_authorization_id)
        assert demo.claimed_run_id == run
        assert incident.expires_at <= demo.expires_at
    with SessionLocal.begin() as db:
        with pytest.raises(IncidentAuthorizationError):
            authorize_incident(
                db, incident_id, WorkflowRun(run, 2, "b" * 40), expected_expires_at=expiry,
                claim=True, require_demo_authorization=True,
            )


def test_revocation_and_expiry_reject_even_previously_claimed_run(enabled_demo):
    incident_id, expiry = accepted_demo(enabled_demo)
    with SessionLocal.begin() as db:
        authorize_incident(
            db, incident_id, WorkflowRun(888, 1, "b" * 40), expected_expires_at=expiry,
            claim=True, require_demo_authorization=True,
        )
    assert enabled_demo.post("/api/alerts/demo/revoke").status_code == 401
    assert enabled_demo.post(
        "/api/alerts/demo/revoke", headers=OWNER_HEADERS,
    ).json() == {"revoked": 1}
    for state, expires in (
        ("revoked", datetime.now(timezone.utc) + timedelta(minutes=5)),
        ("claimed", datetime.now(timezone.utc) - timedelta(seconds=1)),
    ):
        with SessionLocal.begin() as db:
            incident = db.get(AlertIncident, incident_id)
            demo = db.get(DevelopmentDemoAuthorization, incident.demo_authorization_id)
            demo.state = state
            demo.expires_at = expires
        with SessionLocal.begin() as db:
            with pytest.raises(IncidentAuthorizationError):
                authorize_incident(
                    db, incident_id, WorkflowRun(888, 1, "b" * 40),
                    expected_expires_at=expiry, claim=False,
                    require_demo_authorization=False,  # Cannot bypass a durable binding by disabling a flag.
                )


@pytest.mark.parametrize("workflow_sha", ["", "a" * 40, "c" * 40])
def test_claim_requires_immutable_faulty_main_workflow_revision(enabled_demo, workflow_sha):
    incident_id, expiry = accepted_demo(enabled_demo)
    with SessionLocal.begin() as db:
        with pytest.raises(IncidentAuthorizationError):
            authorize_incident(
                db, incident_id, WorkflowRun(123, 1, workflow_sha),
                expected_expires_at=expiry, claim=True, require_demo_authorization=True,
            )
    with SessionLocal() as db:
        assert db.get(AlertIncident, incident_id).execution_claimed_at is None


def test_revoking_does_not_allow_rearming_same_fault_revision(enabled_demo):
    assert enabled_demo.post(
        "/api/alerts/demo/arm", json=arm_body(), headers=OWNER_HEADERS,
    ).status_code == 201
    assert enabled_demo.post(
        "/api/alerts/demo/revoke", headers=OWNER_HEADERS,
    ).status_code == 200
    api_module.limiter.reset()
    assert enabled_demo.post(
        "/api/alerts/demo/arm", json=arm_body(), headers=OWNER_HEADERS,
    ).status_code == 409


def test_emergency_revoke_preserves_legacy_rows_and_revokes_main_after_upgrade(enabled_demo):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    config = Config("alembic.ini")
    command.downgrade(config, "0003_demo_authorization")
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    try:
        def historical_row(identifier, state, fault_revision, **claim):
            return DevelopmentDemoAuthorization(
                id=identifier * 64,
                trusted_revision="a" * 40,
                fault_revision=fault_revision * 40,
                expected_repaired_tree="c" * 40,
                branch="demo/save-recovery",
                backend_digest="sha256:" + "1" * 64,
                frontend_digest="sha256:" + "2" * 64,
                rollback_backend_digest="sha256:" + "3" * 64,
                rollback_frontend_digest="sha256:" + "4" * 64,
                backend_target="https://simple-sudoku-backend.onrender.com",
                frontend_target="https://simple-sudoku-frontend.onrender.com",
                rollback_evidence_url=(
                    "https://github.com/sadevaraj/aidevtools_prj/issues/13"
                    "#issuecomment-999999"
                ),
                state=state,
                expires_at=expired,
                **claim,
            )

        legacy_armed = historical_row("d", "armed", "d")
        legacy_claimed = historical_row(
            "e", "claimed", "e",
            claimed_run_id=99,
            claimed_run_attempt=1,
            claimed_at=expired,
        )
        with SessionLocal.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0003_demo_authorization"
            )
            db.add_all((legacy_armed, legacy_claimed))

        command.upgrade(config, "head")
        incident_id, expiry = accepted_demo(enabled_demo)
        run = WorkflowRun(12345, 1, "b" * 40)
        with SessionLocal.begin() as db:
            authorize_incident(
                db,
                incident_id,
                run,
                expected_expires_at=expiry,
                claim=True,
                require_demo_authorization=True,
            )

        # Reproduce the old unscoped revoke update: NOT VALID exempts the
        # migration scan, not this later write against historical rows.
        with SessionLocal() as db:
            with db.begin():
                for legacy_id in (legacy_armed.id, legacy_claimed.id):
                    with pytest.raises(IntegrityError):
                        with db.begin_nested():
                            db.execute(
                                update(DevelopmentDemoAuthorization)
                                .where(DevelopmentDemoAuthorization.id == legacy_id)
                                .values(state="revoked")
                            )

        response = enabled_demo.post(
            "/api/alerts/demo/revoke", headers=OWNER_HEADERS,
        )

        assert response.status_code == 200
        assert response.json() == {"revoked": 1}
        with SessionLocal() as db:
            historical_armed = db.get(DevelopmentDemoAuthorization, legacy_armed.id)
            historical_claimed = db.get(DevelopmentDemoAuthorization, legacy_claimed.id)
            incident = db.get(AlertIncident, incident_id)
            current = db.get(
                DevelopmentDemoAuthorization, incident.demo_authorization_id,
            )
            assert historical_armed is not None
            assert historical_armed.branch == "demo/save-recovery"
            assert historical_armed.state == "armed"
            assert historical_claimed is not None
            assert historical_claimed.branch == "demo/save-recovery"
            assert historical_claimed.state == "claimed"
            assert historical_claimed.claimed_run_id == 99
            assert {row.id for row in db.scalars(
                select(DevelopmentDemoAuthorization)
            ).all()} == {legacy_armed.id, legacy_claimed.id, incident.demo_authorization_id}
            assert current is not None
            assert current.branch == "main"
            assert current.state == "revoked"

        for claim in (True, False):
            with SessionLocal.begin() as db:
                with pytest.raises(IncidentAuthorizationError):
                    authorize_incident(
                        db,
                        incident_id,
                        run,
                        expected_expires_at=expiry,
                        claim=claim,
                        require_demo_authorization=True,
                    )
    finally:
        command.upgrade(config, "head")


def test_new_main_constraint_and_chain_are_applied_to_disposable_database(enabled_demo):
    from sqlalchemy import text

    with SessionLocal() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0004_main_demo"
        constraint = db.scalar(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_demo_authorization_branch'"
        ))
        assert "'main'" in constraint and "NOT VALID" in constraint
        assert db.scalar(text(
            "SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_demo_main_fault'"
        )) == 1
