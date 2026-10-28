"""Narrow, development-only Grafana receiver and bounded dispatch outbox."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import jwt
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from app.config import load_settings
from app.database import SessionLocal
from app.models import AlertIncident, DevelopmentDemoAuthorization

logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 16_384
INCIDENT_TTL = timedelta(minutes=30)
MAX_ATTEMPTS = 3
MAX_ACCEPTS_PER_MINUTE = 10
ALERT_NAME = "Sudoku save HTTP 5xx"
FINGERPRINT = re.compile(r"^[A-Fa-f0-9]{16,128}$", re.ASCII)
INCIDENT_ID = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_AUDIENCE = "sadevaraj/aidevtools_prj:repair-authorization"
OIDC_JWKS_URL = f"{OIDC_ISSUER}/.well-known/jwks"
MAX_JWKS_BYTES = 32_768
MAX_JWKS_KEYS = 16
JWKS_TTL_SECONDS = 300
JWKS_FAILURE_COOLDOWN_SECONDS = 30
JWKS_TIMEOUT_SECONDS = 5
OIDC_WORKFLOW_REF = (
    "sadevaraj/aidevtools_prj/.github/workflows/pipeline.yml@refs/heads/main"
)
DISPATCH_URL = (
    "https://api.github.com/repos/sadevaraj/aidevtools_prj/"
    "actions/workflows/pipeline.yml/dispatches"
)


class InvalidAlert(ValueError):
    """Untrusted payload does not describe the one supported alert."""


class InvalidWorkflowIdentity(ValueError):
    """Request is not from the one authorized repository workflow."""


class IncidentAuthorizationError(ValueError):
    """Incident is not eligible for this run or has already been consumed."""


class DemoAuthorizationUnavailable(ValueError):
    """No current owner-armed save-recovery demo can receive this alert."""


@dataclass(frozen=True)
class WorkflowRun:
    """GitHub Actions run identity authenticated by its signed OIDC token."""

    run_id: int
    run_attempt: int
    workflow_sha: str = ""


class _NoJwksRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GithubJwksCache:
    """One bounded public-key set per process; no unknown-kid retry storms.

    Only the pinned GitHub endpoint is fetched. A failed refresh fails closed
    (no stale keys) for 30 seconds; successful sets live for at most 5 minutes.
    Rotation may therefore temporarily reject a new key rather than refetching
    on every unauthenticated request. There are no automatic fetch retries.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._keys = {}
        self._expires_at = 0.0
        self._next_fetch_at = 0.0
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoJwksRedirect()
        )

    def get_key(self, kid: str):
        if not isinstance(kid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", kid, re.ASCII):
            raise InvalidWorkflowIdentity
        with self._lock:
            now = time.monotonic()
            if now >= self._expires_at:
                if now < self._next_fetch_at:
                    raise InvalidWorkflowIdentity
                self._keys = {}
                self._next_fetch_at = now + JWKS_FAILURE_COOLDOWN_SECONDS
                try:
                    keys = self._fetch()
                except (OSError, ValueError, TypeError, KeyError, jwt.PyJWTError):
                    raise InvalidWorkflowIdentity from None
                self._keys = keys
                self._expires_at = now + JWKS_TTL_SECONDS
                self._next_fetch_at = self._expires_at
            if kid not in self._keys:
                raise InvalidWorkflowIdentity
            return self._keys[kid]

    def _fetch(self) -> dict:
        deadline = time.monotonic() + JWKS_TIMEOUT_SECONDS
        request = urllib.request.Request(
            OIDC_JWKS_URL, headers={"Accept": "application/json"}
        )
        with self._opener.open(request, timeout=JWKS_TIMEOUT_SECONDS) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ValueError
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_JWKS_BYTES):
                raise ValueError
            data = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError
                chunk = response.read1(min(4096, MAX_JWKS_BYTES + 1 - len(data)))
                if time.monotonic() >= deadline:
                    raise TimeoutError
                data.extend(chunk)
                if len(data) > MAX_JWKS_BYTES:
                    raise ValueError
                if not chunk:
                    break
        payload = json.loads(data)
        keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_JWKS_KEYS:
            raise ValueError
        result = {}
        for key in keys:
            if (
                not isinstance(key, dict)
                or key.get("kty") != "RSA"
                or key.get("use", "sig") != "sig"
                or key.get("alg", "RS256") != "RS256"
                or not isinstance(key.get("kid"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key["kid"], re.ASCII)
                or key["kid"] in result
            ):
                raise ValueError
            result[key["kid"]] = jwt.PyJWK.from_dict(key, algorithm="RS256").key
        return result


_github_jwks = GithubJwksCache()


def verify_github_oidc_token(token: str) -> WorkflowRun:
    """Validate a GitHub Actions token and constrain it to the repair workflow."""
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise InvalidWorkflowIdentity
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise InvalidWorkflowIdentity
        signing_key = _github_jwks.get_key(header["kid"])
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=OIDC_AUDIENCE,
            issuer=OIDC_ISSUER,
            options={
                "require": [
                    "exp",
                    "iat",
                    "aud",
                    "iss",
                    "repository",
                    "ref",
                    "workflow_ref",
                    "workflow_sha",
                    "event_name",
                    "run_id",
                    "run_attempt",
                ]
            },
        )
        if (
            claims["repository"] != "sadevaraj/aidevtools_prj"
            or claims["ref"] != "refs/heads/main"
            or claims["workflow_ref"] != OIDC_WORKFLOW_REF
            or claims["event_name"] != "workflow_dispatch"
            or claims["aud"] != OIDC_AUDIENCE
            or not isinstance(claims["workflow_sha"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", claims["workflow_sha"])
        ):
            raise InvalidWorkflowIdentity
        if isinstance(claims["run_id"], bool) or isinstance(claims["run_attempt"], bool):
            raise InvalidWorkflowIdentity
        run_id = int(claims["run_id"])
        run_attempt = int(claims["run_attempt"])
        if not 0 < run_id <= 9_223_372_036_854_775_807 or not 0 < run_attempt <= 2_147_483_647:
            raise InvalidWorkflowIdentity
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, OSError) as error:
        raise InvalidWorkflowIdentity from error
    return WorkflowRun(run_id=run_id, run_attempt=run_attempt, workflow_sha=claims["workflow_sha"])


def validate_payload(payload: object, *, development: bool) -> str:
    """Return a one-way deduplication key; never retain untrusted payload fields."""
    if not development or not isinstance(payload, dict) or payload.get("status") != "firing":
        raise InvalidAlert
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or len(alerts) != 1:
        raise InvalidAlert
    alert = alerts[0]
    if not isinstance(alert, dict) or alert.get("status") != "firing":
        raise InvalidAlert
    labels = alert.get("labels")
    if not isinstance(labels, dict) or any(
        labels.get(key) != value
        for key, value in {
            "alertname": ALERT_NAME,
            "operation": "save_game",
            "service": "sudoku-api",
            "severity": "warning",
        }.items()
    ):
        raise InvalidAlert
    values = alert.get("values")
    if not isinstance(values, dict) or any(
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 128
        or not (
            type(value) is int
            or (type(value) is float and math.isfinite(value))
        )
        for name, value in values.items()
    ):
        raise InvalidAlert
    evaluated = values.get("A")
    if (
        not (
            type(evaluated) is int
            or (type(evaluated) is float and math.isfinite(evaluated))
        )
        or evaluated <= 0
    ):
        # Error/no-data rule states do not carry the one positive save-error
        # evaluation value, so they cannot be promoted into repair incidents.
        raise InvalidAlert
    fingerprint = alert.get("fingerprint")
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        raise InvalidAlert
    # Stable across notification retries; payload data is not persisted.
    return hashlib.sha256(fingerprint.encode("ascii")).hexdigest()


def accept_incident(
    session, incident_id: str, *, require_demo_authorization: bool = False
) -> bool:
    """Atomically enforce the global intake limit and persist before ACK."""
    now = datetime.now(timezone.utc)
    session.execute(text("SELECT pg_advisory_xact_lock(781230041)"))
    session.execute(delete(AlertIncident).where(AlertIncident.expires_at <= now))
    if session.scalar(
        select(AlertIncident.id).where(AlertIncident.id == incident_id)
    ) is not None:
        session.commit()
        return False
    recent = session.scalar(
        select(func.count()).select_from(AlertIncident).where(
            AlertIncident.created_at >= now - timedelta(minutes=1)
        )
    )
    if recent >= MAX_ACCEPTS_PER_MINUTE:
        raise OverflowError
    demo = None
    if require_demo_authorization:
        demo = session.scalar(
            select(DevelopmentDemoAuthorization)
            .where(
                DevelopmentDemoAuthorization.state == "armed",
                DevelopmentDemoAuthorization.alert_incident_id.is_(None),
                DevelopmentDemoAuthorization.expires_at > now,
            )
            .order_by(DevelopmentDemoAuthorization.expires_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if demo is None:
            raise DemoAuthorizationUnavailable
    result = session.execute(
        insert(AlertIncident)
        .values(
            id=incident_id,
            status="pending",
            attempts=0,
            expires_at=min(now + INCIDENT_TTL, demo.expires_at) if demo else now + INCIDENT_TTL,
            next_attempt_at=now,
            demo_authorization_id=demo.id if demo is not None else None,
        )
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(AlertIncident.id)
    )
    created = result.scalar_one_or_none() is not None
    if created and demo is not None:
        demo.alert_incident_id = incident_id
        demo.state = "claimed"
    session.commit()
    return created


def authorize_incident(
    session,
    incident_id: str,
    run: WorkflowRun,
    *,
    expected_expires_at: str,
    claim: bool,
    require_demo_authorization: bool = False,
) -> datetime:
    """Check trusted DB expiry and atomically bind one workflow attempt."""
    if not INCIDENT_ID.fullmatch(incident_id):
        raise IncidentAuthorizationError
    try:
        expected_expiry = datetime.fromisoformat(
            expected_expires_at.replace("Z", "+00:00")
        )
        if expected_expiry.tzinfo is None:
            raise ValueError
        expected_expiry = expected_expiry.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise IncidentAuthorizationError from None
    now = datetime.now(timezone.utc)
    incident = session.scalar(
        select(AlertIncident)
        .where(AlertIncident.id == incident_id)
        .with_for_update()
    )
    if (
        incident is None
        or incident.expires_at <= now
        or incident.expires_at != expected_expiry
        or incident.attempts < 1
        or incident.status not in {"dispatching", "retry", "dispatched", "failed"}
    ):
        raise IncidentAuthorizationError
    demo = None
    if require_demo_authorization or incident.demo_authorization_id is not None:
        if incident.demo_authorization_id is None:
            raise IncidentAuthorizationError
        demo = session.scalar(
            select(DevelopmentDemoAuthorization)
            .where(DevelopmentDemoAuthorization.id == incident.demo_authorization_id)
            .with_for_update()
        )
        if (
            demo is None
            or demo.state != "claimed"
            or demo.alert_incident_id != incident_id
            or demo.expires_at <= now
            or demo.branch != "main"
            or demo.trusted_revision == demo.fault_revision
            or run.workflow_sha != demo.fault_revision
        ):
            raise IncidentAuthorizationError
    if claim:
        if incident.execution_claimed_at is None:
            incident.execution_run_id = run.run_id
            incident.execution_run_attempt = run.run_attempt
            incident.execution_claimed_at = now
            if demo is not None:
                demo.claimed_run_id = run.run_id
                demo.claimed_run_attempt = run.run_attempt
                demo.claimed_at = now
            session.flush()
        elif (
            incident.execution_run_id != run.run_id
            or incident.execution_run_attempt != run.run_attempt
        ):
            raise IncidentAuthorizationError
    elif (
        incident.execution_run_id != run.run_id
        or incident.execution_run_attempt != run.run_attempt
        or incident.execution_claimed_at is None
    ):
        raise IncidentAuthorizationError
    if demo is not None and (
        demo.claimed_run_id != run.run_id
        or demo.claimed_run_attempt != run.run_attempt
        or demo.claimed_at is None
    ):
        raise IncidentAuthorizationError
    return incident.expires_at


def _claim_incident() -> tuple[str, datetime] | None:
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        incident = session.scalar(
            select(AlertIncident)
            .where(
                AlertIncident.expires_at > now,
                AlertIncident.attempts < MAX_ATTEMPTS,
                AlertIncident.next_attempt_at <= now,
                or_(
                    AlertIncident.status.in_(("pending", "retry")),
                    (
                        (AlertIncident.status == "dispatching")
                        & (AlertIncident.lease_until < now)
                    ),
                ),
            )
            .order_by(AlertIncident.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if incident is None:
            return None
        incident.status = "dispatching"
        incident.attempts += 1
        incident.lease_until = now + timedelta(seconds=60)
        incident.safe_error_code = None
        return incident.id, incident.expires_at


def _dispatch(incident_id: str, expires_at: datetime, bearer_token: str) -> bool:
    request = urllib.request.Request(
        DISPATCH_URL,
        data=json.dumps(
            {
                "ref": "main",
                "inputs": {
                    "mode": "repair",
                    "incident_id": incident_id,
                    "expires_at": expires_at.isoformat(),
                },
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "simple-sudoku-alert-dispatch",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status == 204
    except (urllib.error.URLError, TimeoutError, OSError):
        # Never log the exception: it may contain a URL, response body, or token.
        return False


def _finish_incident(incident_id: str, delivered: bool) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        incident = session.get(AlertIncident, incident_id)
        if incident is None or incident.status != "dispatching":
            return
        incident.lease_until = None
        if delivered:
            incident.status = "dispatched"
            incident.safe_error_code = None
        elif incident.attempts >= MAX_ATTEMPTS or incident.expires_at <= now:
            incident.status = "failed"
            incident.safe_error_code = "dispatch_failed"
        else:
            incident.status = "retry"
            incident.safe_error_code = "dispatch_failed"
            incident.next_attempt_at = now + timedelta(
                seconds=min(10 * (2 ** (incident.attempts - 1)), 60)
            )


def dispatch_once() -> bool:
    settings = load_settings()
    if (
        not settings.alert_repair_enabled
        or settings.app_env != "development"
        or settings.alert_dispatch_token is None
    ):
        return False
    claimed = _claim_incident()
    if claimed is None:
        return False
    incident_id, expires_at = claimed
    delivered = _dispatch(
        incident_id, expires_at, settings.alert_dispatch_token.get_secret_value()
    )
    _finish_incident(incident_id, delivered)
    if not delivered:
        logger.warning("Alert dispatch failed; incident retained for bounded retry.")
    return True


async def _worker() -> None:
    while True:
        try:
            dispatched = await asyncio.to_thread(dispatch_once)
        except Exception as error:
            # Only a fixed code and exception type are safe for diagnostics.
            logger.warning("Alert outbox worker failed (%s).", type(error).__name__)
            dispatched = False
        if not dispatched:
            await asyncio.sleep(5)


@asynccontextmanager
async def alert_lifespan(_app):
    """Run at most one bounded outbox worker per API process."""
    settings = load_settings()
    task = None
    if (
        settings.alert_repair_enabled
        and settings.app_env == "development"
        and settings.alert_dispatch_token is not None
    ):
        task = asyncio.create_task(_worker(), name="sudoku-alert-outbox")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
