"""The special demo probe must never make ordinary failing save CI green."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from app import main as api_module


def test_fault_keeps_the_existing_ordinary_authenticated_save_test_red(tmp_path):
    source = Path(api_module.__file__).parent
    shutil.copytree(source, tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    main = tmp_path / "app/main.py"
    healthy = "game.board = _validated_board(body.board, puzzle.clues)"
    fault = "game.board = _validated_board(body.borad, puzzle.clues)"
    text = main.read_text()
    assert text.count(healthy) == 1
    main.write_text(text.replace(healthy, fault, 1))
    (tmp_path / "tests").mkdir()
    shutil.copyfile(Path(__file__).with_name("test_api.py"), tmp_path / "tests/test_api.py")
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "OTEL_ENABLED": "false"}
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "--tb=short",
            "tests/test_api.py::test_puzzle_list_game_start_save_and_resume_are_persisted_and_owned",
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1, "The ordinary save test must fail on the approved fault."
    assert "1 failed" in result.stdout
    # The ordinary TestClient deliberately propagates server exceptions;
    # the separate immutable regression verifies the HTTP 500 response.
    assert "AttributeError" in result.stdout and "borad" in result.stdout
