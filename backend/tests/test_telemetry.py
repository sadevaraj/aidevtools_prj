"""Observability redaction, trace-correlation, and failure-resilience tests."""

import copy
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, Game, Player
from app.seed_data import PUZZLES
from app.telemetry import (
    DiagnosticSpanExporter,
    SanitizedJsonFormatter,
    _request_metric_attributes,
    _status_outcome,
    logger_provider,
    span_exporter,
    tracer_provider,
)


@pytest.fixture(autouse=True)
def clear_test_rows():
    with SessionLocal.begin() as db:
        db.execute(delete(Game))
        db.execute(delete(AuthSession))
        db.execute(delete(Player))
    yield


def _registered_client(username="TraceUser"):
    client = TestClient(app)
    csrf = client.get("/api/auth/csrf").json()["csrfToken"]
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "RedactionPwd9"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return client, client.cookies["sudoku_csrf"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, "success"),
        (401, "authentication_rejected"),
        (403, "authentication_rejected"),
        (404, "expected_rejection"),
        (409, "expected_conflict"),
        (422, "validation_rejected"),
        (500, "server_error"),
    ],
)
def test_expected_rejections_are_separate_from_server_errors(status, expected):
    assert _status_outcome(status) == expected


def test_metric_dimensions_are_bounded_and_never_include_trace_id():
    dimensions = _request_metric_attributes(
        "PUT", "/api/games/{game_id}", 200, "success"
    )
    assert dimensions == {
        "http.request.method": "PUT",
        "http.route": "/api/games/{game_id}",
        "http.response.status_class": "2xx",
        "sudoku.outcome": "success",
    }
    assert not any("trace" in key.lower() or "request_id" in key.lower() for key in dimensions)
    assert _request_metric_attributes("UNBOUNDED", "/" + "x" * 300, 500, "server_error")[
        "http.request.method"
    ] == "OTHER"


def test_save_trace_continues_through_database_and_logs_are_redacted():
    memory_exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(memory_exporter)
    tracer_provider.add_span_processor(processor)
    log_buffer = io.StringIO()
    capture = logging.StreamHandler(log_buffer)
    capture.setFormatter(SanitizedJsonFormatter())
    request_logger = logging.getLogger("sudoku.request")
    request_logger.addHandler(capture)
    trace_id = "0123456789abcdef0123456789abcdef"
    parent_id = "0123456789abcdef"
    try:
        client, csrf = _registered_client("TraceSentinel")
        game = client.post("/api/games/1", headers={"X-CSRF-Token": csrf}).json()
        board = copy.deepcopy(game["board"])
        header = f"00-{trace_id}-{parent_id}-01"
        saved = client.put(
            f"/api/games/{game['id']}",
            json={"board": board},
            headers={"X-CSRF-Token": csrf, "traceparent": header},
        )
        assert saved.status_code == 200
        unauthenticated = TestClient(app).get("/api/me")
        assert unauthenticated.status_code == 401
        rejected_body = client.post(
            "/api/games/1",
            json={"request_body": "RequestBodySentinel"},
            headers={"X-CSRF-Token": csrf},
        )
        assert rejected_body.status_code == 422
        tracer_provider.force_flush(5000)

        spans = memory_exporter.get_finished_spans()
        request_span = next(span for span in spans if span.name == "PUT /api/games/{game_id}")
        database_span = next(span for span in spans if span.name == "db.save_game")
        assert request_span.context.trace_id == int(trace_id, 16)
        assert request_span.parent.span_id == int(parent_id, 16)
        assert database_span.context.trace_id == request_span.context.trace_id
        assert database_span.parent.span_id == request_span.context.span_id
        assert database_span.attributes["db.system"] == "postgresql"

        with SessionLocal() as db:
            player = db.scalar(select(Player).where(Player.username == "TraceSentinel"))
            session = db.scalar(select(AuthSession).where(AuthSession.player_id == player.id))
            password_hash = player.password_hash
        forbidden = [
            "TraceSentinel",
            "RedactionPwd9",
            password_hash,
            client.cookies["sudoku_session"],
            client.cookies["sudoku_csrf"],
            "DBCredentialSentinel",
            "RequestBodySentinel",
            json.dumps(board, separators=(",", ":")),
            session.token_hash,
        ]
        span_payload = json.dumps([
            {"name": span.name, "attributes": dict(span.attributes)} for span in spans
        ], sort_keys=True)
        assert all(secret not in span_payload for secret in forbidden)
        assert session.token_hash not in log_buffer.getvalue()
        serialized_logs = log_buffer.getvalue()
        assert '"trace_id":"' + trace_id + '"' in serialized_logs
        assert all(secret not in serialized_logs for secret in forbidden)
        assert '"operation":"save_game"' in serialized_logs
        assert '"outcome":"success"' in serialized_logs
        assert '"outcome":"authentication_rejected"' in serialized_logs
        assert '"outcome":"validation_rejected"' in serialized_logs
    finally:
        request_logger.removeHandler(capture)
        capture.close()
        processor.shutdown()


def test_formatter_drops_all_unapproved_sensitive_attributes():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "safe_event", (), None)
    forbidden = {
        "username": "UserSecret",
        "password": "PasswordSecret",
        "password_hash": "HashSecret",
        "session_token": "SessionSecret",
        "csrf_token": "CsrfSecret",
        "cookie": "CookieSecret",
        "database_url": "postgresql://user:DBCredentialSentinel@db/app",
        "request_body": "RequestBodySentinel",
        "board": [[1, 2, 3]],
    }
    for name, value in forbidden.items():
        setattr(record, name, value)
    serialized = SanitizedJsonFormatter().format(record)
    assert json.loads(serialized) == {
        "environment": "development",
        "message": "safe_event",
        "service_name": "sudoku-api",
        "severity": "INFO",
        "timestamp": json.loads(serialized)["timestamp"],
        "version": "0.1.0",
    }
    assert all(secret not in serialized for secret in [
        "UserSecret", "PasswordSecret", "HashSecret", "SessionSecret",
        "CsrfSecret", "CookieSecret", "DBCredentialSentinel", "RequestBodySentinel",
    ])
    assert "board" not in serialized


def test_save_succeeds_when_telemetry_exporter_is_unavailable_and_reports_diagnostic():
    if span_exporter is None:
        pytest.skip("the integration Compose profile enables the intentionally unavailable exporter")
    client, csrf = _registered_client("OutageUser")
    game = client.post("/api/games/1", headers={"X-CSRF-Token": csrf}).json()
    saved = client.put(
        f"/api/games/{game['id']}",
        json={"board": game["board"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200
    assert saved.json()["board"] == PUZZLES[0]["clues"]

    diagnostics = io.StringIO()
    handler = logging.StreamHandler(diagnostics)
    diagnostic_logger = logging.getLogger("sudoku.telemetry.export")
    diagnostic_logger.addHandler(handler)
    try:
        tracer_provider.force_flush(5000)
        logger_provider.force_flush(5000)
    finally:
        diagnostic_logger.removeHandler(handler)
        handler.close()
    assert "telemetry_export_failed signal=traces" in diagnostics.getvalue()


def test_diagnostic_exporter_does_not_emit_exception_content():
    class BrokenExporter:
        def export(self, _spans):
            raise RuntimeError("sensitive exporter payload")

        def shutdown(self):
            return None

    diagnostics = io.StringIO()
    handler = logging.StreamHandler(diagnostics)
    diagnostic_logger = logging.getLogger("sudoku.telemetry.export")
    diagnostic_logger.addHandler(handler)
    try:
        result = DiagnosticSpanExporter(BrokenExporter()).export([])
    finally:
        diagnostic_logger.removeHandler(handler)
        handler.close()
    assert result.name == "FAILURE"
    assert "RuntimeError" in diagnostics.getvalue()
    assert "sensitive exporter payload" not in diagnostics.getvalue()
