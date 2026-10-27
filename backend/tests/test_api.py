"""Real-PostgreSQL API tests; Compose initializes migrations and seeds first."""

import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app, limiter
from app.models import AuthSession, Game, Player
from app.seed_data import PUZZLES
from app.migrate import main as migrate_and_seed
from app.models import Puzzle
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import main as api_module
from app import migrate as migrate_module


@pytest.fixture(autouse=True)
def clear_test_rows():
    limiter.reset()
    with SessionLocal.begin() as db:
        db.execute(delete(Game))
        db.execute(delete(AuthSession))
        db.execute(delete(Player))
    yield


def client_with_csrf():
    client = TestClient(app)
    token = client.get("/api/auth/csrf").json()["csrfToken"]
    return client, token


def register(username="Player1", password="Password1"):
    client, token = client_with_csrf()
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": token},
    )
    return client, client.cookies.get("sudoku_csrf", token), response


def test_register_creates_hash_and_revocable_http_only_session_without_raw_token():
    client, _, response = register()
    assert response.status_code == 201
    assert response.json()["username"] == "Player1"
    cookie = response.cookies.get("sudoku_session")
    assert cookie
    assert "httponly" in response.headers.get("set-cookie", "").lower()
    assert client.get("/api/me").json()["username"] == "Player1"
    with SessionLocal() as db:
        player = db.scalar(select(Player).where(Player.username == "Player1"))
        session = db.scalar(select(AuthSession).where(AuthSession.player_id == player.id))
        assert player.password_hash != "Password1"
        assert "Password1" not in player.password_hash
        assert session.token_hash == hashlib.sha256(cookie.encode()).hexdigest()
        assert cookie not in session.token_hash
        assert session.revoked is False


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", "Password1"),
        ("non-asciié", "Password1"),
        ("waytoolongusername", "Password1"),
        ("valid_user", "short"),
        ("valid_user", "waytoolongpassword"),
    ],
)
def test_registration_rejects_invalid_boundaries(username, password):
    client, token = client_with_csrf()
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(Player.id)) is None


def test_duplicate_username_is_case_insensitive_and_does_not_overwrite():
    _, _, first = register("Mi_Xed", "Password1")
    client, token = client_with_csrf()
    second = client.post(
        "/api/auth/register",
        json={"username": "mi_xed", "password": "Password2"},
        headers={"X-CSRF-Token": token},
    )
    assert first.status_code == 201
    assert second.status_code == 409
    client2, token2 = client_with_csrf()
    login = client2.post(
        "/api/auth/login",
        json={"username": "MI_XED", "password": "Password1"},
        headers={"X-CSRF-Token": token2},
    )
    assert login.status_code == 200


def test_registration_race_cannot_create_case_variant_duplicates():
    def create(username):
        client, token = client_with_csrf()
        return client.post(
            "/api/auth/register",
            json={"username": username, "password": "Password1"},
            headers={"X-CSRF-Token": token},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, ("Race_User", "race_user")))
    assert sorted(outcomes) == [201, 409]
    with SessionLocal() as db:
        assert db.query(Player).count() == 1


def test_csrf_generic_login_failure_rate_limit_and_logout_revocation():
    client, token, created = register()
    assert created.status_code == 201
    assert client.post("/api/auth/logout", json={}, headers={}).status_code == 403
    assert stale_csrf_request_status(client, token) == 403
    stale_client, stale_token = client_with_csrf()
    bad_login = stale_client.post(
        "/api/auth/login",
        json={"username": "missing", "password": "Incorrect1"},
        headers={"X-CSRF-Token": stale_token},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "Invalid username or password."
    for _ in range(5):
        response = stale_client.post(
            "/api/auth/login",
            json={"username": "missing", "password": "Incorrect1"},
            headers={"X-CSRF-Token": stale_token},
        )
    assert response.status_code in {401, 429}
    limited = stale_client.post(
        "/api/auth/login",
        json={"username": "missing", "password": "Incorrect1"},
        headers={"X-CSRF-Token": stale_token},
    )
    assert limited.status_code == 429
    assert client.post("/api/auth/logout", json={}, headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get("/api/me").status_code == 401


def stale_csrf_request_status(client, token):
    return client.post(
        "/api/auth/logout",
        json={},
        headers={"X-CSRF-Token": "forged-" + token},
    ).status_code


def test_puzzle_list_game_start_save_and_resume_are_persisted_and_owned():
    owner, token, response = register()
    assert response.status_code == 201
    puzzles = owner.get("/api/puzzles")
    assert puzzles.status_code == 200 and len(puzzles.json()) == 3
    assert {item["status"] for item in puzzles.json()} == {"unstarted"}
    opened = owner.post("/api/games/1", headers={"X-CSRF-Token": token})
    assert opened.status_code == 200
    game = opened.json()
    assert game["board"] == PUZZLES[0]["clues"]
    board = copy.deepcopy(game["board"])
    row, column = next((r, c) for r in range(9) for c in range(9) if board[r][c] is None)
    board[row][column] = PUZZLES[0]["solution"][row][column]
    saved = owner.put(
        f"/api/games/{game['id']}", json={"board": board}, headers={"X-CSRF-Token": token}
    )
    assert saved.status_code == 200
    resumed = owner.get(f"/api/games/{game['id']}")
    assert resumed.json()["board"] == board

    stranger, stranger_token, _ = register("OtherUser", "Password2")
    assert stranger.get(f"/api/games/{game['id']}").status_code == 404
    assert stranger.put(
        f"/api/games/{game['id']}", json={"board": board}, headers={"X-CSRF-Token": stranger_token}
    ).status_code == 404

    malformed = owner.put(
        f"/api/games/{game['id']}", json={"board": [[None] * 9]}, headers={"X-CSRF-Token": token}
    )
    assert malformed.status_code == 422
    changed_clue = copy.deepcopy(board)
    clue_row, clue_column = next(
        (r, c) for r in range(9) for c in range(9) if game["clues"][r][c] is not None
    )
    changed_clue[clue_row][clue_column] = (game["clues"][clue_row][clue_column] % 9) + 1
    assert owner.put(
        f"/api/games/{game['id']}", json={"board": changed_clue}, headers={"X-CSRF-Token": token}
    ).status_code == 422


def test_deliberate_save_typo_reproduces_500_and_repaired_save_persists(tmp_path):
    """Reproduce in a temporary backend source checkout; never break app.main."""
    source = Path(api_module.__file__).read_text(encoding="utf-8")
    correct_line = "game.board = _validated_board(body.board, puzzle.clues)"
    assert source.count(correct_line) == 1
    broken_source = source.replace(
        correct_line,
        "game.board = _validated_board(body.borad, puzzle.clues)",
        1,
    )
    checkout = tmp_path / "checkout"
    shutil.copytree(
        Path(api_module.__file__).parent,
        checkout / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    isolated_main = checkout / "app" / "main.py"
    isolated_main.write_text(broken_source, encoding="utf-8")
    probe = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, raise_server_exceptions=False) as client:
    token = client.get("/api/auth/csrf").json()["csrfToken"]
    response = client.post(
        "/api/auth/register",
        json={"username": "TypoTest", "password": "Password1"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201
    token = client.cookies["sudoku_csrf"]
    headers = {"X-CSRF-Token": token}
    game = client.post("/api/games/1", headers=headers).json()
    board = [row[:] for row in game["board"]]
    cell = next((r, c) for r in range(9) for c in range(9) if board[r][c] is None)
    board[cell[0]][cell[1]] = 4
    failed = client.put(
        f"/api/games/{game['id']}", json={"board": board}, headers=headers
    )
    assert failed.status_code == 500
    print(game["id"])
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(checkout)
    environment["OTEL_ENABLED"] = "false"
    reproduced = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert reproduced.returncode == 0, "isolated HTTP 500 reproduction failed"
    game_id = int(reproduced.stdout.strip())
    with SessionLocal() as db:
        persisted = db.get(Game, game_id)
        assert persisted.board == PUZZLES[0]["clues"]
        assert persisted.last_saved_at is None

    # The unmodified application represents the corrected body.board handler.
    repaired, token = client_with_csrf()
    login = repaired.post(
        "/api/auth/login",
        json={"username": "TypoTest", "password": "Password1"},
        headers={"X-CSRF-Token": token},
    )
    assert login.status_code == 200
    token = repaired.cookies["sudoku_csrf"]
    game = repaired.get(f"/api/games/{game_id}").json()
    board = copy.deepcopy(game["board"])
    row, column = next(
        (r, c) for r in range(9) for c in range(9) if board[r][c] is None
    )
    board[row][column] = PUZZLES[0]["solution"][row][column]
    saved = repaired.put(
        f"/api/games/{game_id}",
        json={"board": board},
        headers={"X-CSRF-Token": token},
    )
    assert saved.status_code == 200
    assert saved.json()["board"] == board
    with SessionLocal() as db:
        persisted = db.get(Game, game_id)
        assert persisted.board == board
        assert persisted.last_saved_at is not None


def test_concurrent_start_returns_one_persisted_game():
    owner, token, _ = register()
    raw_cookie = owner.cookies.get("sudoku_session")
    csrf_cookie = owner.cookies.get("sudoku_csrf")

    def start():
        client = TestClient(app)
        client.cookies.set("sudoku_session", raw_cookie)
        client.cookies.set("sudoku_csrf", csrf_cookie)
        return client.post("/api/games/2", headers={"X-CSRF-Token": token}).json()["id"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(lambda _: start(), range(6)))
    assert len(set(ids)) == 1
    with SessionLocal() as db:
        assert len(db.scalars(select(Game).where(Game.puzzle_id == 2)).all()) == 1


def test_migration_and_seeds_are_idempotent_and_preserve_existing_game():
    owner, token, _ = register()
    game = owner.post("/api/games/3", headers={"X-CSRF-Token": token}).json()
    migrate_and_seed()
    assert owner.get(f"/api/games/{game['id']}").json()["id"] == game["id"]
    with SessionLocal() as db:
        assert db.query(Player).count() == 1
        assert db.query(Game).count() == 1
        from app.models import Puzzle
        assert db.query(Puzzle).count() == 3


def test_submission_distinguishes_incomplete_incorrect_correct_and_locks_completion():
    owner, token, _ = register()
    game = owner.post("/api/games/1", headers={"X-CSRF-Token": token}).json()
    game_url = f"/api/games/{game['id']}"
    incomplete = owner.post(
        f"{game_url}/submit", json={"board": game["board"]}, headers={"X-CSRF-Token": token}
    )
    assert incomplete.json() == {"result": "incomplete", "status": "in_progress"}

    solution = copy.deepcopy(PUZZLES[0]["solution"])
    wrong = copy.deepcopy(solution)
    r, c = next((r, c) for r in range(9) for c in range(9) if game["clues"][r][c] is None)
    wrong[r][c] = wrong[r][c] % 9 + 1
    incorrect = owner.post(
        f"{game_url}/submit", json={"board": wrong}, headers={"X-CSRF-Token": token}
    )
    assert incorrect.json() == {"result": "incorrect", "status": "in_progress"}
    with SessionLocal() as db:
        assert db.get(Game, game["id"]).status == "in_progress"

    correct = owner.post(
        f"{game_url}/submit", json={"board": solution}, headers={"X-CSRF-Token": token}
    )
    assert correct.json() == {"result": "correct", "status": "completed"}
    repeated_start = owner.post("/api/games/1", headers={"X-CSRF-Token": token})
    assert repeated_start.json()["id"] == game["id"]
    assert repeated_start.json()["status"] == "completed"
    assert owner.put(game_url, json={"board": solution}, headers={"X-CSRF-Token": token}).status_code == 409
    assert owner.post(
        f"{game_url}/submit", json={"board": solution}, headers={"X-CSRF-Token": token}
    ).status_code == 200
    assert owner.get(game_url).json()["status"] == "completed"


@pytest.mark.parametrize(("username", "password"), [
    ("a", "aBc12345"), ("A" * 14, " AbCd12345678 "),
    ("unicode_pw", "😀abcdefg"),
])
def test_valid_boundaries_passwords_are_not_transformed(username, password):
    client, _, response = register(username, password)
    assert response.status_code == 201
    other, token = client_with_csrf()
    assert other.post("/api/auth/login", json={"username": username.swapcase(), "password": password},
                      headers={"X-CSRF-Token": token}).status_code == 200
    for transformed in {password.lower(), password.strip()} - {password}:
        assert other.post("/api/auth/login", json={"username": username, "password": transformed},
                          headers={"X-CSRF-Token": other.cookies["sudoku_csrf"]}).status_code == 401


def test_validation_errors_and_logs_do_not_echo_auth_secrets(caplog):
    client, token = client_with_csrf()
    secret = "PrivateTest9"
    for path, payload in [
        ("/api/auth/register", {"username": [], "password": secret}),
        ("/api/auth/login", {"username": "x", "password": {"secret": secret}}),
        ("/api/auth/register", {"username": "x", "password": secret, "token": secret}),
    ]:
        response = client.post(path, json=payload, headers={"X-CSRF-Token": token})
        assert response.status_code == 422
        assert secret not in response.text
    client, token, response = register("Redacted", secret)
    raw = client.cookies["sudoku_session"]
    with SessionLocal() as db:
        stored_hash = db.scalar(select(Player.password_hash).where(Player.username == "Redacted"))
    assert all(value not in response.text for value in (secret, raw, stored_hash))
    assert all(value not in caplog.text for value in (secret, raw, stored_hash))


def test_secure_cookie_configuration_no_expiry_and_revoked_cookie_replay(monkeypatch):
    monkeypatch.setattr(api_module, "settings", api_module.settings.model_copy(update={"app_env": "production"}))
    client = TestClient(app, base_url="https://testserver")
    token = client.get("/api/auth/csrf").json()["csrfToken"]
    response = client.post("/api/auth/register", json={"username": "Secure", "password": "Password1"},
                           headers={"X-CSRF-Token": token})
    cookies = response.headers.get_list("set-cookie")
    session_header = next(c for c in cookies if c.startswith("sudoku_session="))
    assert all(attr in session_header.lower() for attr in ("httponly", "secure", "samesite=lax"))
    assert "max-age" not in session_header.lower() and "expires" not in session_header.lower()
    raw = client.cookies["sudoku_session"]
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": client.cookies["sudoku_csrf"]}).status_code == 200
    client.cookies.set("sudoku_session", raw)
    assert client.get("/api/me").status_code == 401
    client.cookies.set("sudoku_session", "forged")
    assert client.get("/api/me").status_code == 401


def test_local_http_cookie_override_keeps_httponly_and_samesite(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        api_module.settings.model_copy(update={"cookie_secure": False}),
    )
    client = TestClient(app, base_url="http://testserver")
    token = client.get("/api/auth/csrf").json()["csrfToken"]
    response = client.post(
        "/api/auth/register",
        json={"username": "LocalCookie", "password": "Password1"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201
    cookies = response.headers.get_list("set-cookie")
    session_header = next(cookie for cookie in cookies if cookie.startswith("sudoku_session="))
    assert "httponly" in session_header.lower()
    assert "samesite=lax" in session_header.lower()
    assert "secure" not in session_header.lower()


@pytest.mark.parametrize("path", ["/api/auth/register", "/api/auth/login", "/api/auth/logout",
                                  "/api/games/1", "/api/games/1/submit"])
def test_all_state_changing_routes_reject_missing_or_forged_csrf(path):
    client, token = client_with_csrf()
    assert client.post(path, json={}).status_code == 403
    assert client.post(path, json={}, headers={"X-CSRF-Token": "forged"}).status_code == 403
    client.cookies.set("sudoku_csrf", "forged")
    assert client.post(path, json={}, headers={"X-CSRF-Token": "forged"}).status_code == 403


def test_anonymous_foreign_and_spoofed_requests_cannot_mutate_owned_game():
    owner, token, _ = register()
    game = owner.post("/api/games/1", headers={"X-CSRF-Token": token}).json()
    url = f"/api/games/{game['id']}"
    stranger, foreign_token, _ = register("Stranger")
    anon, anon_token = client_with_csrf()
    for client, csrf, status in [(stranger, foreign_token, 404), (anon, anon_token, 401)]:
        assert client.get(url).status_code == status
        for method, path in [("PUT", url), ("POST", url + "/submit")]:
            assert client.request(method, path, json={"board": game["board"]},
                                  headers={"X-CSRF-Token": csrf}).status_code == status
    assert anon.get("/api/puzzles").status_code == 401
    assert anon.post("/api/games/1", headers={"X-CSRF-Token": anon_token}).status_code == 401
    assert stranger.get("/api/puzzles").json()[0]["gameId"] is None
    assert owner.post("/api/games/99999", headers={"X-CSRF-Token": token}).status_code == 404
    assert stranger.post("/api/games/1", json={"player_id": 1},
                         headers={"X-CSRF-Token": foreign_token}).status_code == 422
    assert owner.put(url, json={"board": game["board"], "status": "completed"},
                     headers={"X-CSRF-Token": token}).status_code == 422
    assert owner.get(url).json() == game


@pytest.mark.parametrize("value", [0, 10, -1, True, "1", 1.5, {}, []])
def test_invalid_cells_save_and_submit_do_not_change_persisted_data(value):
    owner, token, _ = register()
    game = owner.post("/api/games/1", headers={"X-CSRF-Token": token}).json()
    url = f"/api/games/{game['id']}"
    board = copy.deepcopy(game["board"])
    r, c = next((r, c) for r in range(9) for c in range(9) if board[r][c] is None)
    board[r][c] = value
    for method, path in [("PUT", url), ("POST", url + "/submit")]:
        assert owner.request(method, path, json={"board": board},
                             headers={"X-CSRF-Token": token}).status_code == 422
    assert owner.get(url).json() == game


def test_save_failure_rolls_back_and_second_login_resumes_saved_data(monkeypatch):
    owner, token, _ = register()
    game = owner.post("/api/games/1", headers={"X-CSRF-Token": token}).json()
    url = f"/api/games/{game['id']}"
    board = copy.deepcopy(PUZZLES[0]["solution"])
    with monkeypatch.context() as patch:
        def fail_commit(self):
            raise RuntimeError("controlled database failure")
        patch.setattr(Session, "commit", fail_commit)
        with TestClient(app, raise_server_exceptions=False) as failed:
            failed.cookies.update(owner.cookies)
            assert failed.put(url, json={"board": board}, headers={"X-CSRF-Token": token}).status_code == 500
    assert owner.get(url).json() == game
    saved = owner.put(url, json={"board": board}, headers={"X-CSRF-Token": token}).json()
    assert saved["lastSavedAt"] is not None
    other, csrf = client_with_csrf()
    assert other.post("/api/auth/login", json={"username": "player1", "password": "Password1"},
                      headers={"X-CSRF-Token": csrf}).status_code == 200
    assert other.get(url).json()["board"] == board


def test_concurrent_save_submit_cannot_overwrite_completion():
    owner, token, _ = register()
    game = owner.post("/api/games/1", headers={"X-CSRF-Token": token}).json()
    url = f"/api/games/{game['id']}"
    def write(submit):
        client = TestClient(app)
        client.cookies.update(owner.cookies)
        return client.request("POST" if submit else "PUT", url + ("/submit" if submit else ""),
                              json={"board": PUZZLES[0]["solution"] if submit else game["board"]},
                              headers={"X-CSRF-Token": token}).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(write, [False, True, False, True, False, True]))
    assert set(outcomes) <= {200, 409}
    persisted = owner.get(url).json()
    assert persisted["status"] == "completed"
    assert persisted["board"] == PUZZLES[0]["solution"]
    assert persisted["completedAt"] is not None
    for suffix in ("/reset", "/restart"):
        assert owner.post(url + suffix, headers={"X-CSRF-Token": token}).status_code in {404, 405}
    assert owner.get(url).json() == persisted


def test_database_constraints_reject_duplicates_without_api():
    owner, token, response = register()
    game = owner.post("/api/games/1", headers={"X-CSRF-Token": token}).json()
    with SessionLocal() as db:
        db.add(Player(username="pLAYER1", password_hash="test-only-noncredential"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(Game(player_id=response.json()["id"], puzzle_id=1, board=game["board"]))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_migration_failure_and_seed_failure_are_fatal_and_seed_rolls_back(monkeypatch):
    with monkeypatch.context() as patch:
        def fail_upgrade(*args):
            raise RuntimeError("controlled migration failure")
        patch.setattr(migrate_module.command, "upgrade", fail_upgrade)
        with pytest.raises(RuntimeError, match="controlled migration failure"):
            migrate_and_seed()
    # Empty only the isolated test database seeds; failed partial seed must roll back.
    with SessionLocal.begin() as db:
        db.execute(delete(Puzzle))
    broken = copy.deepcopy(PUZZLES)
    broken[1]["solution"][0][0] = broken[1]["solution"][0][1]
    with monkeypatch.context() as patch:
        patch.setattr(migrate_module, "PUZZLES", broken)
        with pytest.raises(RuntimeError, match="validation"):
            migrate_and_seed()
    with SessionLocal() as db:
        assert db.query(Puzzle).count() == 0
    migrate_and_seed()


def test_incorrect_submission_preserves_saved_state_and_remains_editable():
    owner, token, _ = register()
    headers = {"X-CSRF-Token": token}
    game = owner.post("/api/games/1", headers=headers).json()
    url = f"/api/games/{game['id']}"
    board = copy.deepcopy(game["board"])
    r, c = next((r, c) for r in range(9) for c in range(9) if board[r][c] is None)
    board[r][c] = PUZZLES[0]["solution"][r][c]
    saved = owner.put(url, json={"board": board}, headers=headers).json()
    wrong = copy.deepcopy(PUZZLES[0]["solution"])
    wrong[r][c] = wrong[r][c] % 9 + 1
    result = owner.post(url + "/submit", json={"board": wrong}, headers=headers)
    assert result.status_code == 200
    assert result.json() == {"result": "incorrect", "status": "in_progress"}
    assert owner.get(url).json() == saved
    assert saved["completedAt"] is None
    assert owner.get("/api/puzzles").json()[0]["status"] == "in_progress"
    # Incorrect submission does not implicitly save; an explicit subsequent save works.
    edited = owner.put(url, json={"board": wrong}, headers=headers)
    assert edited.status_code == 200
    assert edited.json()["board"] == wrong
    assert edited.json()["completedAt"] is None


def test_completed_game_is_durable_and_read_only_in_separate_authenticated_session():
    owner, token, _ = register()
    game = owner.post("/api/games/1", headers={"X-CSRF-Token": token}).json()
    url = f"/api/games/{game['id']}"
    solution = PUZZLES[0]["solution"]
    assert owner.post(url + "/submit", json={"board": solution},
                      headers={"X-CSRF-Token": token}).status_code == 200
    completed = owner.get(url).json()
    assert completed["board"] == solution
    assert completed["status"] == "completed"
    assert completed["completedAt"] is not None
    assert completed["lastSavedAt"] == completed["completedAt"]

    second, csrf = client_with_csrf()
    assert second.get(url).status_code == 401
    assert second.post("/api/auth/login",
                       json={"username": "PLAYER1", "password": "Password1"},
                       headers={"X-CSRF-Token": csrf}).status_code == 200
    assert second.cookies["sudoku_session"] != owner.cookies["sudoku_session"]
    headers = {"X-CSRF-Token": second.cookies["sudoku_csrf"]}
    assert second.get(url).json() == completed
    assert second.get("/api/puzzles").json()[0]["status"] == "completed"
    assert second.post("/api/games/1", headers=headers).json() == completed
    assert second.put(url, json={"board": game["board"]}, headers=headers).status_code == 409
    # A stale repeat submit must never replace the durable completed board or timestamps.
    assert second.post(url + "/submit", json={"board": game["board"]},
                       headers=headers).status_code == 200
    assert second.get(url).json() == completed
    with SessionLocal() as db:
        persisted = db.get(Game, game["id"])
        assert persisted.board == solution
        assert persisted.status == "completed"
        assert persisted.completed_at is not None
        assert db.query(Game).count() == 1


@pytest.mark.parametrize("operation", ["save", "submit"])
def test_flushed_write_failure_rolls_back_board_status_and_timestamps(monkeypatch, operation):
    owner, token, _ = register()
    headers = {"X-CSRF-Token": token}
    game = owner.post("/api/games/1", headers=headers).json()
    url = f"/api/games/{game['id']}"
    original = owner.put(url, json={"board": game["board"]}, headers=headers).json()
    flushed = []

    def fail_after_flush(db):
        # Send the UPDATE to real PostgreSQL before failing, rather than merely
        # raising before SQLAlchemy has written anything.
        db.flush()
        pending = db.get(Game, game["id"])
        assert pending.board == PUZZLES[0]["solution"]
        assert pending.status == ("completed" if operation == "submit" else "in_progress")
        flushed.append(True)
        raise RuntimeError("controlled post-flush failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        with TestClient(app, raise_server_exceptions=False) as failed:
            failed.cookies.update(owner.cookies)
            response = failed.request(
                "PUT" if operation == "save" else "POST",
                url if operation == "save" else url + "/submit",
                json={"board": PUZZLES[0]["solution"]}, headers=headers,
            )
            assert response.status_code == 500
    assert flushed == [True]
    assert owner.get(url).json() == original
    with SessionLocal() as db:
        persisted = db.get(Game, game["id"])
        assert persisted.board == original["board"]
        assert persisted.status == "in_progress"
        assert persisted.completed_at is None
    # The failed transaction releases the row lock and a later operation succeeds.
    assert owner.post(url + "/submit", json={"board": PUZZLES[0]["solution"]},
                      headers=headers).json()["status"] == "completed"
