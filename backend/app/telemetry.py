"""Sanitized OpenTelemetry instrumentation for local Sudoku observability."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, Request
from opentelemetry import metrics, propagate, trace
from opentelemetry.context import Context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogExportResult
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult, SpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExportResult, PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as OTLPGrpcMetricExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPHttpMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

_OTLP_SIGNALS = ("traces", "metrics", "logs")
_HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_OTLP_INTERNAL_LOGGER = logging.getLogger("opentelemetry.exporter.otlp")
_OTLP_INTERNAL_LOGGER.setLevel(logging.CRITICAL + 1)

SERVICE_NAME = "sudoku-api"
SERVICE_VERSION = "0.1.0"
ENVIRONMENT = os.getenv("APP_ENV", "development")


class _CurrentStderrHandler(logging.StreamHandler):
    """Keep asynchronous diagnostics on the live stderr stream after test capture."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


_diagnostic = logging.getLogger("sudoku.telemetry.export")
_diagnostic.setLevel(logging.ERROR)
_diagnostic.propagate = False
if not _diagnostic.handlers:
    _diagnostic.addHandler(_CurrentStderrHandler())


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


@dataclass(frozen=True)
class CloudExporterConfig:
    """Validated OTLP/HTTP settings without exposing header values in errors."""

    endpoints: dict[str, str]
    headers: dict[str, dict[str, str]] = field(repr=False)


def _parse_otlp_headers(raw: str, variable: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw:
        return headers
    for item in raw.split(","):
        name, separator, value = item.partition("=")
        if not separator:
            raise RuntimeError(f"{variable} must contain comma-separated name=value headers")
        name = unquote(name).strip()
        value = unquote(value).strip()
        if (
            not _HTTP_HEADER_NAME.fullmatch(name)
            or not value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise RuntimeError(f"{variable} contains an invalid header")
        headers[name.lower()] = value
    return headers


def _validate_https_endpoint(endpoint: str, variable: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        # Accessing .port also validates malformed/out-of-range port values.
        _ = parsed.port
    except ValueError:
        raise RuntimeError(f"{variable} must be a valid HTTPS OTLP endpoint") from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(f"{variable} must be a valid HTTPS OTLP endpoint")
    return endpoint


def _validate_local_endpoints(environment: dict[str, str]) -> None:
    """Trust only the named Compose collector and explicit loopback defaults.

    Private IP ranges, DNS suffixes, and arbitrary gRPC resolver targets do not
    establish that a destination is the repository's local collector.
    """
    hosts = ("otel-collector", "127.0.0.1", "localhost", "[::1]")
    http_variable = "OTEL_EXPORTER_OTLP_ENDPOINT"
    if environment.get(http_variable, "http://127.0.0.1:4318").rstrip("/") not in {
        f"http://{host}:4318" for host in hosts
    }:
        raise RuntimeError(
            f"{http_variable} must use a supported local collector or authenticated HTTPS cloud mode"
        )
    grpc_variable = "OTEL_EXPORTER_OTLP_GRPC_ENDPOINT"
    if environment.get(grpc_variable, "127.0.0.1:4317") not in {
        f"{host}:4317" for host in hosts
    }:
        raise RuntimeError(
            f"{grpc_variable} must use a supported local collector; remote metrics require HTTPS cloud mode"
        )
    for signal in _OTLP_SIGNALS:
        variable = f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT"
        if variable in environment:
            raise RuntimeError(
                f"{variable} requires authenticated HTTPS cloud mode; local mode uses the shared collector"
            )


def _cloud_export_config(environment: dict[str, str]) -> CloudExporterConfig | None:
    """Load standard OTLP/HTTP environment variables for explicit cloud mode."""
    protocol = environment.get("OTEL_EXPORTER_OTLP_PROTOCOL", "").strip().lower()
    if not protocol:
        header_variables = (
            "OTEL_EXPORTER_OTLP_HEADERS",
            *(f"OTEL_EXPORTER_OTLP_{signal.upper()}_HEADERS" for signal in _OTLP_SIGNALS),
        )
        if any(environment.get(variable) for variable in header_variables):
            raise RuntimeError(
                "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf is required when OTLP headers are set"
            )
        endpoint_variables = (
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            *(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT" for signal in _OTLP_SIGNALS),
        )
        if any(
            environment.get(variable, "").strip().lower().startswith("https://")
            for variable in endpoint_variables
        ):
            raise RuntimeError(
                "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf is required for HTTPS OTLP endpoints"
            )
        _validate_local_endpoints(environment)
        return None
    if protocol != "http/protobuf":
        raise RuntimeError("OTEL_EXPORTER_OTLP_PROTOCOL must be http/protobuf for cloud export")

    endpoints: dict[str, str] = {}
    headers: dict[str, dict[str, str]] = {}
    for signal in _OTLP_SIGNALS:
        signal_upper = signal.upper()
        endpoint_variable = f"OTEL_EXPORTER_OTLP_{signal_upper}_ENDPOINT"
        if endpoint_variable in environment:
            endpoint = environment[endpoint_variable]
            variable = endpoint_variable
        else:
            endpoint = environment.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
            variable = "OTEL_EXPORTER_OTLP_ENDPOINT"
            if endpoint:
                # The standard generic HTTP endpoint is a base URL; append the
                # signal path once. Signal-specific endpoints are used as-is.
                endpoint = f"{endpoint.rstrip('/')}/v1/{signal}"
        if not endpoint:
            raise RuntimeError(f"{variable} is required for cloud export")
        endpoints[signal] = _validate_https_endpoint(endpoint, variable)

        headers_variable = f"OTEL_EXPORTER_OTLP_{signal_upper}_HEADERS"
        if headers_variable in environment:
            raw_headers = environment[headers_variable]
            variable = headers_variable
        else:
            raw_headers = environment.get("OTEL_EXPORTER_OTLP_HEADERS", "")
            variable = "OTEL_EXPORTER_OTLP_HEADERS"
        signal_headers = _parse_otlp_headers(raw_headers, variable)
        if "authorization" not in signal_headers:
            raise RuntimeError(f"{variable} must provide an Authorization header for {signal} export")
        headers[signal] = signal_headers

    return CloudExporterConfig(endpoints=endpoints, headers=headers)


class DiagnosticExporter:
    """Keep each signal's export failures visible without logging payloads."""

    def __init__(
        self,
        exporter: Any,
        signal: str,
        success_result: Any,
        failure_result: Any,
    ) -> None:
        self._exporter = exporter
        self._signal = signal
        self._success_result = success_result
        self._failure_result = failure_result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._exporter, name)

    def _report_failure(self, error: Exception | None = None) -> None:
        if error is None:
            _diagnostic.error(
                "telemetry_export_failed signal=%s result=failure", self._signal
            )
        else:
            _diagnostic.error(
                "telemetry_export_failed signal=%s failure_type=%s",
                self._signal,
                type(error).__name__,
            )

    def export(self, *args: Any, **kwargs: Any) -> Any:
        try:
            result = self._exporter.export(*args, **kwargs)
        except Exception as error:
            self._report_failure(error)
            return self._failure_result
        if result is not self._success_result:
            self._report_failure()
        return result

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        try:
            self._exporter.shutdown(*args, **kwargs)
        except Exception as error:
            self._report_failure(error)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        force_flush = getattr(self._exporter, "force_flush", None)
        try:
            success = bool(force_flush(timeout_millis)) if force_flush else True
        except Exception as error:
            self._report_failure(error)
            return False
        if not success:
            self._report_failure()
        return success


class DiagnosticSpanExporter(DiagnosticExporter, SpanExporter):
    """Compatibility wrapper for the tracing exporter."""

    def __init__(self, exporter: SpanExporter) -> None:
        super().__init__(
            exporter,
            "traces",
            SpanExportResult.SUCCESS,
            SpanExportResult.FAILURE,
        )


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


def _create_exporters(
    cloud_config: CloudExporterConfig | None,
) -> tuple[DiagnosticSpanExporter, DiagnosticExporter, DiagnosticExporter]:
    if cloud_config is None:
        span = OTLPSpanExporter(endpoint=_endpoint("/v1/traces"), timeout=2)
        metric = OTLPGrpcMetricExporter(
            endpoint=os.getenv("OTEL_EXPORTER_OTLP_GRPC_ENDPOINT", "127.0.0.1:4317"),
            timeout=2,
            insecure=True,
        )
        log = OTLPLogExporter(endpoint=_endpoint("/v1/logs"), timeout=2)
    else:
        span = OTLPSpanExporter(
            endpoint=cloud_config.endpoints["traces"],
            headers=cloud_config.headers["traces"],
            timeout=2,
        )
        metric = OTLPHttpMetricExporter(
            endpoint=cloud_config.endpoints["metrics"],
            headers=cloud_config.headers["metrics"],
            timeout=2,
        )
        log = OTLPLogExporter(
            endpoint=cloud_config.endpoints["logs"],
            headers=cloud_config.headers["logs"],
            timeout=2,
        )
    return (
        DiagnosticSpanExporter(span),
        DiagnosticExporter(metric, "metrics", MetricExportResult.SUCCESS, MetricExportResult.FAILURE),
        DiagnosticExporter(log, "logs", LogExportResult.SUCCESS, LogExportResult.FAILURE),
    )


_resource_value = _resource()
tracer_provider = TracerProvider(resource=_resource_value)
tracer = tracer_provider.get_tracer("sudoku.api", SERVICE_VERSION)
_telemetry_enabled = os.getenv("OTEL_ENABLED", "false").lower() == "true"
span_exporter: DiagnosticSpanExporter | None = None
if _telemetry_enabled:
    cloud_config = _cloud_export_config(dict(os.environ))
    span_exporter, metric_exporter, log_exporter = _create_exporters(cloud_config)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter, schedule_delay_millis=1000))
    reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=5000,
    )
    meter_provider = MeterProvider(resource=_resource_value, metric_readers=[reader])
    logger_provider = LoggerProvider(resource=_resource_value)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            log_exporter,
            schedule_delay_millis=1000,
        )
    )
else:
    metric_exporter = None
    log_exporter = None
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
