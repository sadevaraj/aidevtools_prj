"""Focused contract and mock-delivery tests for the Grafana-managed save alert."""

import json
import re
import shutil
import socket
import ssl
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ALERT_DIR = ROOT / "observability" / "grafana-cloud-alert"
CONTRACT = json.loads((ALERT_DIR / "alert-contract.json").read_text())
TERRAFORM = "\n".join(
    path.read_text()
    for path in sorted(ALERT_DIR.glob("*.tf"))
)


def _fires_for_save_outcomes(outcomes, now):
    """Model the bounded server_error counter queried by the PromQL contract."""
    window_start = now - timedelta(minutes=5)
    return any(
        operation == "save_game"
        and 500 <= status <= 599
        and window_start < timestamp <= now
        for operation, status, timestamp in outcomes
    )


def test_rule_contract_is_save_5xx_only_and_uses_a_rolling_five_minute_window():
    assert CONTRACT["expression"] == (
        'sum(count_over_time({service_name="sudoku-api"} | json | operation="save_game" | outcome="server_error" [5m])) > 0'
    )
    assert re.search(r'no_data_state\s*=\s*"OK"', TERRAFORM)
    assert re.search(r'for\s*=\s*"0s"', TERRAFORM)
    assert re.search(r"max_alerts\s*=\s*1", TERRAFORM)


def test_zero_4xx_only_non_save_5xx_and_out_of_window_events_do_not_fire():
    now = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
    assert not _fires_for_save_outcomes([], now)
    assert not _fires_for_save_outcomes(
        [
            ("save_game", 400, now - timedelta(seconds=30)),
            ("save_game", 401, now - timedelta(minutes=1)),
            ("save_game", 403, now - timedelta(minutes=1, seconds=30)),
            ("save_game", 404, now - timedelta(minutes=2)),
            ("save_game", 422, now - timedelta(minutes=2)),
            ("save_game", 409, now - timedelta(minutes=3)),
        ],
        now,
    )
    assert not _fires_for_save_outcomes(
        [("api_request", 500, now - timedelta(minutes=1))],
        now,
    )
    assert not _fires_for_save_outcomes(
        [("save_game", 500, now - timedelta(minutes=5, seconds=1))],
        now,
    )


def test_one_save_5xx_inside_window_fires_immediately():
    now = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
    assert _fires_for_save_outcomes(
        [("save_game", 500, now - timedelta(minutes=4, seconds=59))],
        now,
    )


def test_alert_metadata_and_contact_point_configuration_are_bounded_and_private():
    assert CONTRACT["labels"] == {
        "operation": "save_game",
        "service": "sudoku-api",
        "severity": "warning",
    }
    assert set(CONTRACT["annotations"]) == {"summary", "description"}
    assert re.search(r'authorization_scheme\s*=\s*"Bearer"', TERRAFORM)
    assert "authorization_credentials = var.webhook_bearer_token" in TERRAFORM
    assert "sensitive   = true" in TERRAFORM
    assert "insecure_skip_verify = true" not in TERRAFORM
    assert "insecureSkipVerify = true" not in TERRAFORM
    assert 'regex("^https://[^/@\\\\s]+([/?#]|$)"' in TERRAFORM
    assert "error_message = \"webhook_url must be an HTTPS URL without user-info or a fragment.\"" in TERRAFORM


def test_malformed_webhook_configuration_is_rejected_with_generic_diagnostics():
    pattern_source = re.search(r'can\(regex\("([^"]+)"', TERRAFORM)
    assert pattern_source is not None
    pattern = pattern_source.group(1).replace("\\\\", "\\")
    error_message = (
        'webhook_url must be an HTTPS URL without user-info or a fragment.'
    )

    def valid_endpoint(value):
        return (
            len(value) <= 2048
            and re.search(pattern, value) is not None
            and "#" not in value
        )

    assert valid_endpoint("https://127.0.0.1:8443/alerts")
    assert valid_endpoint("https://receiver.example.test/alerts?token=private")
    malformed_values = (
        "http://receiver.example.test/alerts",
        "https://user:password@receiver.example.test/alerts",
        "https://receiver.example.test/alerts#fragment",
        "https://receiver.example.test/" + "x" * 2048,
    )
    for malformed in malformed_values:
        assert not valid_endpoint(malformed)
        assert malformed not in error_message
    assert "private" not in error_message


class _MockReceiver(HTTPServer):
    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.received = []
        self.response_status = 200
        self.expected_authorization = None


class _MockReceiverHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        authorization = self.headers.get("Authorization")
        self.server.received.append(
            (authorization, json.loads(raw_body))
        )
        status = self.server.response_status
        if (
            self.server.expected_authorization is not None
            and authorization != self.server.expected_authorization
        ):
            status = 401
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"PRIVATE_RESPONSE_BODY_SENTINEL")

    def log_message(self, _format, *_args):
        return


def _send_mock_notification(url, bearer_token, payload, tls_context):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Authorization": "Bearer" + " " + bearer_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, context=tls_context, timeout=3) as response:
            return f"webhook delivery succeeded (HTTP status {response.status})"
    except urllib.error.HTTPError as error:
        error.close()
        return f"webhook delivery failed (HTTP status {error.code})"
    except (urllib.error.URLError, ssl.SSLError, socket.timeout):
        return "webhook delivery failed (TLS or connection error)"


@pytest.fixture
def https_mock_receiver(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL CLI is unavailable for disposable HTTPS mock setup")
    certificate = tmp_path / "mock-cert.pem"
    private_key = tmp_path / "mock-key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    server = _MockReceiver(("127.0.0.1", 0), _MockReceiverHandler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, private_key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client_context = ssl.create_default_context(cafile=str(certificate))
        yield (
            server,
            f"https://127.0.0.1:{server.server_port}/alerts",
            client_context,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _firing_payload():
    return {
        "receiver": "Simple Sudoku save failures (HTTPS webhook)",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": CONTRACT["labels"],
                "annotations": CONTRACT["annotations"],
                "startsAt": "2026-10-27T08:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": "fixed-alert-fingerprint",
            }
        ],
        "version": "4",
    }


def test_https_webhook_accepts_authorized_bounded_metadata_only_notification(
    https_mock_receiver,
):
    receiver, url, context = https_mock_receiver
    token = "DISPOSABLE_MOCK_BEARER_TOKEN"
    receiver.expected_authorization = "Bearer" + " " + token

    diagnostic = _send_mock_notification(url, token, _firing_payload(), context)

    assert diagnostic == "webhook delivery succeeded (HTTP status 200)"
    assert len(receiver.received) == 1
    authorization, payload = receiver.received[0]
    assert authorization == "Bearer" + " " + token
    assert len(payload["alerts"]) == 1
    serialized = json.dumps(payload, sort_keys=True)
    forbidden = (
        token,
        "username",
        "game_id",
        "player_id",
        "board",
        "request_body",
        "trace_id",
        "secret",
        "authorization",
        "headers",
        "session",
        "csrf",
        "cookie",
        "password",
        "PRIVATE_RESPONSE_BODY_SENTINEL",
    )
    assert all(value not in serialized for value in forbidden)


def test_webhook_auth_failure_reports_status_without_credentials_or_body(
    https_mock_receiver,
):
    receiver, url, context = https_mock_receiver
    token = "DISPOSABLE_MOCK_BEARER_TOKEN"
    receiver.expected_authorization = "Bearer" + " " + token

    diagnostic = _send_mock_notification(url, "wrong-test-token", _firing_payload(), context)

    assert diagnostic == "webhook delivery failed (HTTP status 401)"
    assert token not in diagnostic
    assert "wrong-test-token" not in diagnostic
    assert "PRIVATE_RESPONSE_BODY_SENTINEL" not in diagnostic


def test_delivery_failure_is_safe_and_does_not_expose_response_body_or_token(
    https_mock_receiver,
):
    receiver, url, context = https_mock_receiver
    receiver.response_status = 503
    token = "DISPOSABLE_MOCK_BEARER_TOKEN"

    diagnostic = _send_mock_notification(url, token, _firing_payload(), context)

    assert diagnostic == "webhook delivery failed (HTTP status 503)"
    assert token not in diagnostic
    assert "PRIVATE_RESPONSE_BODY_SENTINEL" not in diagnostic


def test_untrusted_https_certificate_is_rejected_by_verifying_client(https_mock_receiver):
    _, url, _ = https_mock_receiver
    untrusted_context = ssl.create_default_context()

    diagnostic = _send_mock_notification(
        url, "DISPOSABLE_MOCK_BEARER_TOKEN", _firing_payload(), untrusted_context
    )

    assert diagnostic == "webhook delivery failed (TLS or connection error)"
