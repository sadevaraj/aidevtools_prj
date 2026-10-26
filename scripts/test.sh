#!/bin/sh
set -eu

tempo_datasource="observability/grafana/provisioning/datasources/datasources.yaml"
if [ ! -d observability ]; then
  echo "Required observability directory is missing." >&2
  exit 1
fi
if [ ! -f "$tempo_datasource" ]; then
  echo "Required Grafana datasource file is missing: $tempo_datasource" >&2
  exit 1
fi

# Grafana truncates trace-to-logs ranges to whole milliseconds, while Loki
# stores nanosecond timestamps written when a request span finishes. Require a
# bounded cushion so the trace-ID-filtered link includes the correlated log.
awk '
    function to_ms(value,    number, unit) {
      if (value !~ /^-?[0-9]+(ms|s|m)$/) return "invalid"
      number = value; sub(/(ms|s|m)$/, "", number)
      unit = value; sub(/^-?[0-9]+/, "", unit)
      if (unit == "ms") return number + 0
      if (unit == "s") return number * 1000
      return number * 60000
    }
    /^[[:space:]]+spanStartTimeShift:/ { gsub(/"/, "", $2); start = to_ms($2) }
    /^[[:space:]]+spanEndTimeShift:/ { gsub(/"/, "", $2); end = to_ms($2) }
    /^[[:space:]]+filterByTraceID: true$/ { trace_filter = 1 }
    END {
      if (start == "" || end == "" || start == "invalid" || end == "invalid") {
        print "Tempo trace-to-logs shifts must be set as ms, s, or m durations." > "/dev/stderr"; exit 1
      }
      if (start > -1000 || start < -300000 || end < 1000 || end > 300000) {
        print "Tempo trace-to-logs shifts must pad each side by 1s to 5m." > "/dev/stderr"; exit 1
      }
      if (!trace_filter) {
        print "Tempo trace-to-logs must keep filtering by trace ID." > "/dev/stderr"; exit 1
      }
      # Issue #15 QA reproduction: span ended in millisecond 1793042907910 and
      # the matching log was stored 640 ns later in that millisecond.
      span_end_ms = 1793042907910.000640 - 0.000640
      log_ms = 1793042907910.000640
      if (int(span_end_ms + end) < log_ms || int(span_end_ms + start) > log_ms) {
        print "Tempo trace-to-logs range excludes the reproduced log timestamp." > "/dev/stderr"; exit 1
      }
    }
' "$tempo_datasource"

project="sudoku-isolated-tests-$$"
compose="docker compose -p $project -f compose.test.yaml"

cleanup() {
  $compose down --remove-orphans
}
trap cleanup EXIT INT TERM

$compose up --build --abort-on-container-exit --exit-code-from api_tests api_tests
$compose run --build --rm --no-deps frontend_tests
