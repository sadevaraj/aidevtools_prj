#!/bin/sh
set -eu

project="sudoku-isolated-tests-$$"
compose="docker compose -p $project -f compose.test.yaml"

cleanup() {
  $compose down --remove-orphans
}
trap cleanup EXIT INT TERM

$compose up --build --abort-on-container-exit --exit-code-from api_tests api_tests
$compose run --build --rm --no-deps frontend_tests
