"""Exercise orchestration failure propagation without operating Docker."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize(("fail_stage", "expected"), [("", 0), ("up", 23), ("run", 24)])
def test_root_runner_propagates_failures_and_always_cleans_own_project(tmp_path, fail_stage, expected):
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
    result = subprocess.run(
        ["sh", str(script)], capture_output=True, text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "CALL_LOG": str(log), "FAIL_STAGE": fail_stage},
    )
    assert result.returncode == expected
    calls = log.read_text().splitlines()
    assert calls[-1].endswith("down --remove-orphans")
    assert all("sudoku-isolated-tests-" in call for call in calls)
    assert all("compose.test.yaml" in call and "-v" not in call for call in calls)
    assert not any(" run " in call for call in calls) if fail_stage == "up" else True
