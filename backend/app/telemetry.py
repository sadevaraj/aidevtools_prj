"""Sanitized OpenTelemetry instrumentation for local Sudoku observability."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Sequence

from fastapi import FastAPI, Request
from opentelemetry import metrics, propagate, trace
from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult, SpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

SERVICE_NAME = "sudoku-api"
SERVICE_VERSION = "0.1.0"
ENVIRONMENT = os.getenv("APP_ENV", "development")
_diagnostic = logging.getLogger("sudoku.telemetry.export")
_diagnostic.setLevel(logging.ERROR)
_diagnostic.propagate = False
if not _diagnostic.handlers:
    _diagnostic.addHandler(logging.StreamHandler())


class SanitizedJsonFormatter(logging.Formatter):
    """Serialize only explicitly-approved fields, never a whole log record."""

    def format(self, record: logging.LogRecord) -> str:
        allowed = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "severity": record.levelname,
            "message": record.getMessage(),
            "service_name": SERVICE_NAME,
            "environment": ENVIRONMENT,
            "version": SERVICE_VERSION,
        }
        for key in (
            "trace_id", "span_id", "operation", "outcome", "route",
            "method", "status_class", "duration_ms",
        ):
            value = getattr(record, key, None)
            if value is not None:
                allowed[key] = value
        return json.dumps(allowed, separators=(",", ":"), sort_keys=True)


class DiagnosticSpanExporter(SpanExporter):
    """Keep export failures visible without logging exception or request data."""

    def __init__(self, exporter: SpanExporter) -> None:
        self._exporter = exporter

    def export(self, spans: Sequence[Any]) -> SpanExportResult:
        try:
            result = self._exporter.export(spans)
        except Exception as error:
            _diagnostic.error(
                "telemetry_export_failed signal=traces failure_type=%s",
                type(error).__name__,
            )
            return SpanExportResult.FAILURE
        if result is not SpanExportResult.SUCCESS:
            _diagnostic.error("telemetry_export_failed signal=traces result=failure")
        return result

    def shutdown(self) -> None:
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        force_flush = getattr(self._exporter, "force_flush", None)
        return bool(force_flush(timeout_millis)) if force_flush else True


def _resource() -> Resource:
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": SERVICE_VERSION,
            "deployment.environment": ENVIRONMENT,
        }
    )


def _endpoint(path: str) -> str:
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318").rstrip("/")
    return f"{base}{path}"


_resource_value = _resource()
tracer_provider = TracerProvider(resource=_resource_value)
tracer = tracer_provider.get_tracer("sudoku.api", SERVICE_VERSION)
_telemetry_enabled = os.getenv("OTEL_ENABLED", "false").lower() == "true"
span_exporter: DiagnosticSpanExporter | None = None
if _telemetry_enabled:
    span_exporter = DiagnosticSpanExporter(
        OTLPSpanExporter(endpoint=_endpoint("/v1/traces"), timeout=2)
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter, schedule_delay_millis=1000))
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=os.getenv("OTEL_EXPORTER_OTLP_GRPC_ENDPOINT", "127.0.0.1:4317"),
            timeout=2,
            insecure=True,
        ),
        export_interval_millis=5000,
    )
    meter_provider = MeterProvider(resource=_resource_value, metric_readers=[reader])
    logger_provider = LoggerProvider(resource=_resource_value)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=_endpoint("/v1/logs"), timeout=2),
            schedule_delay_millis=1000,
        )
    )
else:
    meter_provider = MeterProvider(resource=_resource_value)
    logger_provider = LoggerProvider(resource=_resource_value)
trace.set_tracer_provider(tracer_provider)
metrics.set_meter_provider(meter_provider)
propagate.set_global_textmap(TraceContextTextMapPropagator())

_meter = metrics.get_meter("sudoku.api", SERVICE_VERSION)
http_requests = _meter.create_counter(
    "sudoku_http_requests", unit="{request}", description="HTTP request outcomes"
)
http_duration = _meter.create_histogram(
    "sudoku_http_request_duration", unit="s", description="HTTP request latency"
)
save_requests = _meter.create_counter(
    "sudoku_save_requests", unit="{request}", description="Manual game-save outcomes"
)
_app_logger = logging.getLogger("sudoku.request")
_app_logger.setLevel(logging.INFO)
_app_logger.propagate = False
if not any(isinstance(handler, logging.StreamHandler) for handler in _app_logger.handlers):
    handler = logging.StreamHandler()
    handler.setFormatter(SanitizedJsonFormatter())
    _app_logger.addHandler(handler)
if _telemetry_enabled and not any(isinstance(handler, LoggingHandler) for handler in _app_logger.handlers):
    _app_logger.addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))


def _status_outcome(status: int) -> str:
    if 200 <= status < 400:
        return "success"
    if status in {401, 403}:
        return "authentication_rejected"
    if status == 422:
        return "validation_rejected"
    if status == 409:
        return "expected_conflict"
    if 400 <= status < 500:
        return "expected_rejection"
    return "server_error"


def _request_metric_attributes(method: str, route: str, status: int, outcome: str) -> dict[str, str]:
    """Return bounded dimensions only; request and trace IDs are never dimensions."""
    allowed_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER"}
    if method not in allowed_methods:
        method = "OTHER"
    if len(route) > 120 or not route.startswith("/"):
        route = "unmatched"
    return {
        "http.request.method": method,
        "http.route": route,
        "http.response.status_class": f"{status // 100}xx",
        "sudoku.outcome": outcome,
    }


def instrument_app(app: FastAPI) -> None:
    """Record sanitized request spans, bounded metrics, and structured logs."""

    @app.middleware("http")
    async def observe_request(request: Request, call_next: Any):
        started = time.perf_counter()
        parent: Context = propagate.extract(dict(request.headers))
        status = 500
        with tracer.start_as_current_span(
            "http.server.request",
            context=parent,
            kind=SpanKind.SERVER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                response = await call_next(request)
                status = response.status_code
                return response
            finally:
                elapsed = max(0.0, time.perf_counter() - started)
                route_obj = request.scope.get("route")
                route = getattr(route_obj, "path", "unmatched")
                if not isinstance(route, str) or len(route) > 120:
                    route = "unmatched"
                method = request.method if request.method in {
                    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"
                } else "OTHER"
                outcome = _status_outcome(status)
                status_class = f"{status // 100}xx"
                operation = (
                    "save_game"
                    if method == "PUT" and route == "/api/games/{game_id}"
                    else "api_request"
                )
                span.update_name(f"{method} {route}")
                span.set_attribute("http.request.method", method)
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                span.set_attribute("sudoku.operation", operation)
                span.set_attribute("sudoku.outcome", outcome)
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                attributes = _request_metric_attributes(method, route, status, outcome)
                http_requests.add(1, attributes)
                http_duration.record(elapsed, attributes)
                if operation == "save_game":
                    save_requests.add(1, {"outcome": outcome})
                current = trace.get_current_span().get_span_context()
                _app_logger.info(
                    "http_request",
                    extra={
                        "trace_id": f"{current.trace_id:032x}" if current.is_valid else "",
                        "span_id": f"{current.span_id:016x}" if current.is_valid else "",
                        "operation": operation,
                        "outcome": outcome,
                        "route": route,
                        "method": method,
                        "status_class": status_class,
                        "duration_ms": round(elapsed * 1000, 3),
                    },
                )
