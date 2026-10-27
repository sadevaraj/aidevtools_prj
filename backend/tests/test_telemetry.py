"""Observability redaction, trace-correlation, and failure-resilience tests."""

import copy
import io
import json
import logging
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPHttpMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as OTLPGrpcMetricExporter
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.sdk._logs import LogRecord, LoggerProvider as SDKLoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogExporter, LogExportResult, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, MetricExportResult
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models import AuthSession, Game, Player
from app.seed_data import PUZZLES
from app.telemetry import (
    DiagnosticExporter,
    DiagnosticSpanExporter,
    SanitizedJsonFormatter,
    _cloud_export_config,
    _create_exporters,
    _request_metric_attributes,
    _status_outcome,
    log_exporter,
    logger_provider,
    metric_exporter,
    meter_provider,
    span_exporter,
    tracer_provider,
)
from opentelemetry.trace import TraceFlags, set_span_in_context


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


def test_save_succeeds_when_telemetry_exporters_fail_and_reports_safe_diagnostics(monkeypatch):
    if span_exporter is None or metric_exporter is None or log_exporter is None:
        pytest.skip("the integration Compose profile enables the intentionally unavailable exporter")

    class BrokenExporter:
        def export(self, *_args, **_kwargs):
            raise RuntimeError("private exporter failure detail")

        def shutdown(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(span_exporter, "_exporter", BrokenExporter())
    monkeypatch.setattr(metric_exporter, "_exporter", BrokenExporter())
    monkeypatch.setattr(log_exporter, "_exporter", BrokenExporter())

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
        meter_provider.force_flush(5000)
    finally:
        diagnostic_logger.removeHandler(handler)
        handler.close()
    output = diagnostics.getvalue()
    assert "telemetry_export_failed signal=traces" in output
    assert "telemetry_export_failed signal=logs" in output
    assert "telemetry_export_failed signal=metrics" in output
    assert "private exporter failure detail" not in output


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


def test_cloud_otlp_http_uses_standard_endpoint_headers_and_verified_tls():
    config = _cloud_export_config(
        {
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp-gateway.example.net/otlp/",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic%20YWJjZA%3D%3D",
        }
    )
    assert config is not None
    assert "YWJjZA" not in repr(config)
    expected_endpoints = {
        "traces": "https://otlp-gateway.example.net/otlp/v1/traces",
        "metrics": "https://otlp-gateway.example.net/otlp/v1/metrics",
        "logs": "https://otlp-gateway.example.net/otlp/v1/logs",
    }
    assert config.endpoints == expected_endpoints

    exporters = _create_exporters(config)
    try:
        for signal, wrapper in zip(("traces", "metrics", "logs"), exporters):
            exporter = wrapper._exporter
            assert exporter._endpoint == expected_endpoints[signal]
            assert exporter._headers["authorization"] == "Basic YWJjZA=="
            assert exporter._session.verify is True
    finally:
        for exporter in exporters:
            exporter.shutdown()


def test_cloud_otlp_signal_specific_endpoint_and_headers_are_used_as_is():
    environment = {
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://ignored.example.net/otlp",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20generic",
    }
    for signal in ("TRACES", "METRICS", "LOGS"):
        environment[f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT"] = (
            f"https://{signal.lower()}.example.net/custom/v1/{signal.lower()}"
        )
        environment[f"OTEL_EXPORTER_OTLP_{signal}_HEADERS"] = (
            f"Authorization=Bearer%20{signal.lower()}-credential"
        )

    config = _cloud_export_config(environment)
    assert config is not None
    exporters = _create_exporters(config)
    try:
        for signal, wrapper in zip(("traces", "metrics", "logs"), exporters):
            exporter = wrapper._exporter
            assert exporter._endpoint == environment[
                f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT"
            ]
            assert exporter._headers["authorization"] == f"Bearer {signal}-credential"
    finally:
        for exporter in exporters:
            exporter.shutdown()


@pytest.mark.parametrize(
    ("environment", "expected_error", "secret"),
    [
        (
            {"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc", "OTEL_EXPORTER_OTLP_HEADERS": "token=do-not-log"},
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "do-not-log",
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.example.net/otlp",
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20private",
            },
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "private",
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example.net/otlp",
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20private",
            },
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "private",
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.example.net/otlp",
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization",
            },
            "OTEL_EXPORTER_OTLP_HEADERS",
            "Authorization",
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://private-token@collector.example.net/otlp",
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20private",
            },
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "private-token",
        ),
    ],
)
def test_invalid_cloud_otlp_configuration_is_explicit_and_sanitized(
    environment, expected_error, secret
):
    with pytest.raises(RuntimeError) as raised:
        _cloud_export_config(environment)
    assert expected_error in str(raised.value)
    assert secret not in str(raised.value)


def test_cloud_otlp_requires_authorization_on_every_signal():
    environment = {
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.example.net/otlp",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20shared",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "X-Workspace=workspace",
    }
    with pytest.raises(RuntimeError, match="OTEL_EXPORTER_OTLP_LOGS_HEADERS"):
        _cloud_export_config(environment)


def test_telemetry_disabled_ignores_cloud_exporter_configuration():
    secret = "PRIVATE_OTLP_HEADER_SENTINEL"
    environment = os.environ.copy()
    environment.update(
        {
            "OTEL_ENABLED": "false",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "not-a-supported-protocol",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://invalid.example.net",
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization={secret}",
        }
    )
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.telemetry as t; print(t.span_exporter is None, t.metric_exporter is None, t.log_exporter is None)",
        ],
        env=environment,
        capture_output=True,
        check=True,
        text=True,
    )
    assert check.stdout.strip() == "True True True"
    assert secret not in check.stdout + check.stderr


def test_local_otlp_exporter_configuration_stays_http_traces_logs_and_grpc_metrics(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_GRPC_ENDPOINT", "127.0.0.1:4317")
    assert _cloud_export_config({}) is None
    assert _cloud_export_config(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318"}
    ) is None
    exporters = _create_exporters(None)
    try:
        assert exporters[0]._exporter._endpoint == "http://127.0.0.1:4318/v1/traces"
        assert isinstance(exporters[1]._exporter, OTLPGrpcMetricExporter)
        assert exporters[1]._exporter._endpoint == "127.0.0.1:4317"
        assert exporters[2]._exporter._endpoint == "http://127.0.0.1:4318/v1/logs"
    finally:
        for exporter in exporters:
            exporter.shutdown()


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://telemetry.example.invalid/otlp"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://10.0.0.8:4318"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.internal:4318"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector.example.invalid:4318"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://private-user:private-pass@localhost:4318"),
        ("OTEL_EXPORTER_OTLP_GRPC_ENDPOINT", "telemetry.example.invalid:4317"),
        ("OTEL_EXPORTER_OTLP_GRPC_ENDPOINT", "dns:///telemetry.example.invalid:4317"),
        ("OTEL_EXPORTER_OTLP_GRPC_ENDPOINT", "10.0.0.8:4317"),
        *[
            (f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT", "http://telemetry.example.invalid/secret-path")
            for signal in ("TRACES", "METRICS", "LOGS")
        ],
    ],
)
def test_local_mode_rejects_remote_endpoints_before_any_exporter_is_constructed(variable, value):
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("OTEL_")
    }
    environment.update({"OTEL_ENABLED": "true", variable: value})
    # Fail on construction rather than transport: no external export is possible
    # even when reproducing this regression against the broken implementation.
    script = """
import importlib
def forbidden_constructor(*args, **kwargs):
    raise AssertionError("exporter constructed before validation")
for module_name, class_name in (
    ("opentelemetry.exporter.otlp.proto.http.trace_exporter", "OTLPSpanExporter"),
    ("opentelemetry.exporter.otlp.proto.http.metric_exporter", "OTLPMetricExporter"),
    ("opentelemetry.exporter.otlp.proto.grpc.metric_exporter", "OTLPMetricExporter"),
    ("opentelemetry.exporter.otlp.proto.http._log_exporter", "OTLPLogExporter"),
):
    setattr(importlib.import_module(module_name), class_name, forbidden_constructor)
try:
    import app.telemetry
except RuntimeError as error:
    print(str(error))
else:
    raise AssertionError("unsupported endpoint accepted")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "local configuration was not rejected before exporter construction"
    assert variable in result.stdout
    assert value not in result.stdout + result.stderr
    assert "private-user" not in result.stdout + result.stderr
    assert "private-pass" not in result.stdout + result.stderr
    assert "secret-path" not in result.stdout + result.stderr


@pytest.mark.parametrize("host", ["otel-collector", "127.0.0.1", "localhost", "[::1]"])
def test_supported_local_collector_endpoints_are_accepted(host):
    assert _cloud_export_config(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://{host}:4318",
            "OTEL_EXPORTER_OTLP_GRPC_ENDPOINT": f"{host}:4317",
        }
    ) is None


def test_all_signal_export_failures_are_safe_and_metric_exemplars_are_serialized():
    remote_error = "PRIVATE_REMOTE_ERROR_BODY_SENTINEL"
    auth_value = "Bearer PRIVATE_AUTH_HEADER_SENTINEL"

    class ErrorResponse:
        ok = False
        status_code = 401
        text = remote_error
        reason = "Unauthorized"
        headers = {}

    class FailingSession:
        def __init__(self):
            self.headers = {}
            self.verify = True
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return ErrorResponse()

        def close(self):
            return None

    sessions = [FailingSession(), FailingSession(), FailingSession()]
    exporters = (
        DiagnosticSpanExporter(
            OTLPSpanExporter(
                endpoint="https://collector.example.net/v1/traces",
                headers={"authorization": auth_value},
                session=sessions[0],
                timeout=1,
            )
        ),
        DiagnosticExporter(
            OTLPHttpMetricExporter(
                endpoint="https://collector.example.net/v1/metrics",
                headers={"authorization": auth_value},
                session=sessions[1],
                timeout=1,
            ),
            "metrics",
            MetricExportResult.SUCCESS,
            MetricExportResult.FAILURE,
        ),
        DiagnosticExporter(
            OTLPLogExporter(
                endpoint="https://collector.example.net/v1/logs",
                headers={"authorization": auth_value},
                session=sessions[2],
                timeout=1,
            ),
            "logs",
            LogExportResult.SUCCESS,
            LogExportResult.FAILURE,
        ),
    )

    span_provider = SDKTracerProvider()
    span = span_provider.get_tracer("test").start_span("safe-export-test")
    span.end()

    metric_reader = InMemoryMetricReader()
    metric_provider = SDKMeterProvider(metric_readers=[metric_reader])
    counter = metric_provider.get_meter("test").create_counter("test.counter")
    metric_span = span_provider.get_tracer("test").start_span("metric-exemplar")
    counter.add(1, context=set_span_in_context(metric_span))
    metric_span.end()
    metrics_data = metric_reader.get_metrics_data()

    log_provider = SDKLoggerProvider()
    memory_log_exporter = InMemoryLogExporter()
    log_provider.add_log_record_processor(SimpleLogRecordProcessor(memory_log_exporter))
    log_provider.get_logger("test").emit(
        LogRecord(
            trace_id=0,
            span_id=0,
            trace_flags=TraceFlags(0),
            body="safe-test-record",
            severity_number=SeverityNumber.INFO,
        )
    )
    log_data = memory_log_exporter.get_finished_logs()

    diagnostics = io.StringIO()
    diag_handler = logging.StreamHandler(diagnostics)
    diagnostic_logger = logging.getLogger("sudoku.telemetry.export")
    diagnostic_logger.addHandler(diag_handler)
    exporter_logs = io.StringIO()
    root_handler = logging.StreamHandler(exporter_logs)
    root_logger = logging.getLogger()
    root_logger.addHandler(root_handler)
    try:
        results = (
            exporters[0].export([span]),
            exporters[1].export(metrics_data),
            exporters[2].export(log_data),
        )
    finally:
        diagnostic_logger.removeHandler(diag_handler)
        diag_handler.close()
        root_logger.removeHandler(root_handler)
        root_handler.close()
        for exporter in exporters:
            exporter.shutdown()
        span_provider.shutdown()
        metric_provider.shutdown()
        log_provider.shutdown()

    assert [result.name for result in results] == ["FAILURE", "FAILURE", "FAILURE"]
    assert [call[0] for session in sessions for call in session.calls] == [
        "https://collector.example.net/v1/traces",
        "https://collector.example.net/v1/metrics",
        "https://collector.example.net/v1/logs",
    ]
    assert all(session.headers["authorization"] == auth_value for session in sessions)
    assert all(call[1].get("verify", True) is not False for session in sessions for call in session.calls)

    request = ExportMetricsServiceRequest()
    request.ParseFromString(sessions[1].calls[0][1]["data"])
    proto_exemplars = [
        exemplar
        for resource_metrics in request.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        for point in getattr(metric, metric.WhichOneof("data")).data_points
        for exemplar in point.exemplars
    ]
    assert proto_exemplars

    safe_diagnostics = diagnostics.getvalue()
    assert all(f"signal={signal}" in safe_diagnostics for signal in ("traces", "metrics", "logs"))
    assert remote_error not in safe_diagnostics + exporter_logs.getvalue()
    assert auth_value not in safe_diagnostics + exporter_logs.getvalue()
