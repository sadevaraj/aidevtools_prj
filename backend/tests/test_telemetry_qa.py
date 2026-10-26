"""Independent issue #15 regression checks for telemetry privacy."""

import json

from sqlalchemy.exc import StatementError
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.telemetry import tracer, tracer_provider

def test_database_failure_does_not_export_statement_parameters(monkeypatch):
    """Exercise the real save handler with a representative bound-parameter DB error."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session
    from app.main import app
    client = TestClient(app, raise_server_exceptions=False)
    csrf = client.get("/api/auth/csrf").json()["csrfToken"]
    registered = client.post(
        "/api/auth/register",
        json={"username": "QA15FailSave", "password": "QaFixture15Pwd"},
        headers={"X-CSRF-Token": csrf},
    )
    assert registered.status_code == 201
    headers = {"X-CSRF-Token": client.cookies["sudoku_csrf"]}
    game = client.post("/api/games/1", headers=headers).json()
    marker = "QA15_PRIVATE_BOUND_PARAMETER"
    def failed_commit(_session):
        raise StatementError(
            "database save failed", "UPDATE games SET board=:board",
            {"board": marker}, RuntimeError("connection interrupted"),
        )
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    tracer_provider.add_span_processor(processor)
    try:
        monkeypatch.setattr(Session, "commit", failed_commit)
        response = client.put(
            f"/api/games/{game['id']}", json={"board": game["board"]}, headers=headers,
        )
        assert response.status_code == 500
        spans = exporter.get_finished_spans()
        database_span = next(span for span in spans if span.name == "db.save_game")
        assert database_span.status.status_code.name == "ERROR"
        assert database_span.attributes["error.type"] == "StatementError"
        assert not database_span.events
        payload = json.dumps([
            {
                "name": span.name,
                "attributes": dict(span.attributes),
                "status": span.status.description,
                "events": [
                    {"name": event.name, "attributes": dict(event.attributes)}
                    for event in span.events
                ],
            }
            for span in spans
        ])
        leaked = marker in payload
        assert not leaked, "Real save failure exported a private bound database parameter"
    finally:
        processor.shutdown()


def test_csrf_rejected_save_is_observed_as_authentication_rejection():
    from fastapi.testclient import TestClient
    from app.main import app
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    tracer_provider.add_span_processor(processor)
    try:
        response = TestClient(app).put("/api/games/1", json={"board": []})
        assert response.status_code == 403
        spans = exporter.get_finished_spans()
        request_span = next(
            span for span in spans if span.attributes.get("http.response.status_code") == 403
        )
        assert request_span.attributes["sudoku.outcome"] == "authentication_rejected"
        assert request_span.attributes["http.response.status_code"] == 403
    finally:
        processor.shutdown()
