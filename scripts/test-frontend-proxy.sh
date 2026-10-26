#!/bin/sh
set -eu

# Disposable local TLS material only; never use deployment certificates/keys.
certificates="$(mktemp -d)"
project="sudoku-proxy-tests-$$"
export PROXY_TEST_CERTIFICATES="$certificates"
compose="docker compose --env-file /dev/null -p $project -f compose.proxy-test.yaml"
cleanup() {
  $compose down --remove-orphans
  rm -rf "$certificates"
}
trap cleanup EXIT INT TERM

for name in trusted untrusted; do
  openssl genrsa -out "$certificates/$name.key" 2048
  openssl req -new -x509 -key "$certificates/$name.key" -days 1 \
    -subj /CN=proxy-fixture -addext subjectAltName=DNS:proxy-fixture \
    -out "$certificates/$name.crt"
done

$compose up --build --abort-on-container-exit --exit-code-from proxy_tests
