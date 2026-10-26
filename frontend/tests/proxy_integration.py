"""Real production nginx regression tests using disposable HTTP/TLS fixtures."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
import sys
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit


COOKIE = "session=synthetic-session; csrf_token=synthetic-csrf"
SET_COOKIE = "session=synthetic-session; Path=/; HttpOnly; Secure; SameSite=Lax"
TRACEPARENT = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Do not log request headers, cookies, or bodies.

    def do_GET(self):
        expected_host = f"proxy-fixture:{self.server.server_port}"
        status = 200 if self.headers.get("Host") == expected_host else 421
        if self.path.startswith("/api/status"):
            status = int(parse_qs(urlsplit(self.path).query)["code"][0])
        self.reply(status)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.headers.get("Cookie") != COOKIE:
            status = 401
        elif self.headers.get("X-CSRF-Token") != "synthetic-csrf":
            status = 403
        elif body != b'{"value":1}':
            status = 422
        else:
            status = 200
        self.reply(status, body.decode())

    def reply(self, status, body=""):
        payload = json.dumps({
            "path": self.path,
            "host": self.headers.get("Host"),
            "sni": getattr(self.connection, "sni", None),
            "cookie": self.headers.get("Cookie"),
            "csrf": self.headers.get("X-CSRF-Token"),
            "origin": self.headers.get("Origin"),
            "traceparent": self.headers.get("traceparent"),
            "tracestate": self.headers.get("tracestate"),
            "forwarded_proto": self.headers.get("X-Forwarded-Proto"),
            "body": body,
        }).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", SET_COOKIE)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve():
    def record_sni(connection, name, _context):
        if not name:
            raise ssl.SSLError("SNI required by test fixture")
        connection.sni = name

    servers = []
    for port, certificate in [(8000, None), (8443, "trusted"), (9443, "untrusted")]:
        server = ThreadingHTTPServer(("0.0.0.0", port), Fixture)
        if certificate:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(
                f"/certificates/{certificate}.crt",
                f"/certificates/{certificate}.key",
            )
            context.set_servername_callback(record_sni)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()


class ProxyTests(unittest.TestCase):
    @staticmethod
    def request(service, path="/api/health", method="GET", headers=None, body=None):
        connection = http.client.HTTPConnection(service, 10000, timeout=5)
        try:
            connection.request(method, path, body=body, headers={
                "Host": "frontend.example.test",
                **(headers or {}),
            })
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    @classmethod
    def setUpClass(cls):
        for service in ("proxy_https", "proxy_http", "proxy_untrusted", "proxy_mismatch"):
            for attempt in range(60):
                try:
                    cls.request(service)
                    break
                except (OSError, http.client.HTTPException):
                    if attempt == 59:
                        raise
                    time.sleep(0.5)

    def test_https_host_sni_and_request_response_context(self):
        status, headers, body = self.request(
            "proxy_https", "/api/health?probe=1",
            headers={
                "Cookie": COOKIE,
                "X-CSRF-Token": "synthetic-csrf",
                "Origin": "https://frontend.example.test",
                "traceparent": TRACEPARENT,
                "tracestate": "test=value",
            },
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["host"], "proxy-fixture:8443")
        self.assertEqual(data["sni"], "proxy-fixture")
        self.assertEqual(data["path"], "/api/health?probe=1")
        self.assertEqual(data["cookie"], COOKIE)
        self.assertEqual(data["csrf"], "synthetic-csrf")
        self.assertEqual(data["origin"], "https://frontend.example.test")
        self.assertEqual(data["traceparent"], TRACEPARENT)
        self.assertEqual(data["tracestate"], "test=value")
        self.assertEqual(data["forwarded_proto"], "http")  # Existing behavior.
        self.assertEqual(headers["Set-Cookie"], SET_COOKIE)  # No domain rewriting.

    def test_local_http_upstream_and_static_frontend(self):
        status, _, body = self.request("proxy_http")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["host"], "proxy-fixture:8000")
        self.assertIsNone(data["sni"])
        status, _, body = self.request("proxy_http", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'<div id="root">', body)

    def test_untrusted_certificate_fails_closed(self):
        self.assertEqual(self.request("proxy_untrusted")[0], 502)

    def test_certificate_hostname_mismatch_fails_closed(self):
        self.assertEqual(self.request("proxy_mismatch")[0], 502)

    def test_authorization_csrf_invalid_input_and_success_passthrough(self):
        cases = [
            ({}, b'{"value":1}', 401),
            ({"Cookie": COOKIE}, b'{"value":1}', 403),
            ({"Cookie": COOKIE, "X-CSRF-Token": "synthetic-csrf"}, b"invalid", 422),
            ({"Cookie": COOKIE, "X-CSRF-Token": "synthetic-csrf"}, b'{"value":1}', 200),
        ]
        for service in ("proxy_https", "proxy_http"):
            for headers, body, expected in cases:
                with self.subTest(service=service, expected=expected):
                    status, _, payload = self.request(
                        service, "/api/save", "POST", headers, body,
                    )
                    self.assertEqual(status, expected)
                    self.assertEqual(json.loads(payload)["body"], body.decode())

    def test_backend_failure_passthrough(self):
        status, _, body = self.request("proxy_https", "/api/status?code=500")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body)["path"], "/api/status?code=500")


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        serve()
    else:
        unittest.main()
