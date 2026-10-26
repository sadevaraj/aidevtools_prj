"""Exercise orchestration failure propagation without operating Docker."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def runner_project(tmp_path):
    """Copy the runner into a self-contained project, as in the backend image."""
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$CALL_LOG"\n'
        'case " $* " in\n'
        '  *" up "*) [ "$FAIL_STAGE" != up ] || exit 23 ;;\n'
        '  *" run "*) [ "$FAIL_STAGE" != run ] || exit 24 ;;\n'
        "esac\nexit 0\n"
    )
    docker.chmod(0o755)
    log = tmp_path / "calls"
    script = Path(__file__).resolve().parents[1] / "scripts/test.sh"
    if not script.exists():
        script = Path(__file__).resolve().parents[2] / "scripts/test.sh"
    copied_script = tmp_path / "scripts/test.sh"
    copied_script.parent.mkdir()
    copied_script.write_text(script.read_text())
    datasource = tmp_path / "observability/grafana/provisioning/datasources/datasources.yaml"
    datasource.parent.mkdir(parents=True)
    # Orchestration fixtures need valid input, not a production validation bypass.
    datasource.write_text(
        'datasources:\n'
        '  - jsonData:\n'
        '      tracesToLogsV2:\n'
        '        spanStartTimeShift: "-1m"\n'
        '        spanEndTimeShift: "1m"\n'
        '        filterByTraceID: true\n'
    )

    def run(fail_stage=""):
        return subprocess.run(
            ["sh", str(copied_script)], cwd=tmp_path, capture_output=True, text=True,
            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
                 "CALL_LOG": str(log), "FAIL_STAGE": fail_stage},
        )

    return run, datasource, log


@pytest.mark.parametrize(("fail_stage", "expected"), [("", 0), ("up", 23), ("run", 24)])
def test_root_runner_propagates_failures_and_always_cleans_own_project(runner_project, fail_stage, expected):
    run, _, log = runner_project
    result = run(fail_stage)
    assert result.returncode == expected
    calls = log.read_text().splitlines()
    assert calls[-1].endswith("down --remove-orphans")
    assert all("sudoku-isolated-tests-" in call for call in calls)
    assert all("compose.test.yaml" in call and "-v" not in call for call in calls)
    assert not any(" run " in call for call in calls) if fail_stage == "up" else True


@pytest.mark.parametrize("missing", ["directory", "file"])
def test_root_runner_requires_observability_config_before_docker(runner_project, missing):
    run, datasource, log = runner_project
    if missing == "directory":
        observability = datasource.parents[3]
        observability.rename(observability.with_name("observability-renamed"))
        message = "Required observability directory is missing."
    else:
        datasource.unlink()
        message = "Required Grafana datasource file is missing:"

    result = run()

    assert result.returncode == 1
    assert message in result.stderr
    assert not log.exists(), "No Docker command should run with missing config"


@pytest.mark.parametrize(
    ("start", "end"),
    [("-1m", "1m"), ("-30s", "10s"), ("-1s", "1s"),
     ("-1000ms", "1000ms"), ("-5m", "5m")],
)
def test_root_runner_accepts_bounded_trace_to_logs_shifts(runner_project, start, end):
    run, datasource, log = runner_project
    datasource.write_text(
        datasource.read_text()
        .replace('"-1m"', f'"{start}"')
        .replace('"1m"', f'"{end}"')
    )

    result = run()

    assert result.returncode == 0, result.stderr
    assert len(log.read_text().splitlines()) == 3


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('"-1m"', '"0s"', "pad each side"),
        ('"1m"', '"0s"', "pad each side"),
        ('"-1m"', '"-1ms"', "pad each side"),
        ('"1m"', '"500ms"', "pad each side"),
        ('"-1m"', '"1m"', "pad each side"),
        ('"1m"', '"-1m"', "pad each side"),
        ('"-1m"', '"-6m"', "pad each side"),
        ('"1m"', '"6m"', "pad each side"),
        ('"1m"', '"1h"', "must be set"),
        ('"-1m"', '"invalid"', "must be set"),
        ('"1m"', '"1x"', "must be set"),
        ('        spanStartTimeShift: "-1m"\n', "", "must be set"),
        ('        spanEndTimeShift: "1m"\n', "", "must be set"),
        ("filterByTraceID: true", "filterByTraceID: false", "filtering by trace ID"),
        ("        filterByTraceID: true\n", "", "filtering by trace ID"),
    ],
)
def test_root_runner_rejects_invalid_trace_to_logs_config(runner_project, old, new, message):
    run, datasource, log = runner_project
    original = datasource.read_text()
    assert old in original
    datasource.write_text(original.replace(old, new))

    result = run()

    assert result.returncode == 1
    assert message in result.stderr
    assert not log.exists(), "No Docker command should run with invalid config"
