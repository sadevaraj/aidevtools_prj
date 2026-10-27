"""Simple Sudoku API with database-backed accounts and games."""

import hashlib
import logging
import secrets
import re
import json
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from pwdlib import PasswordHash
from opentelemetry.trace import Status, StatusCode

from app.config import load_settings
from app.database import get_db
from app.models import AuthSession, Game, Player, Puzzle
from app.sudoku import is_complete, is_valid_solution, preserves_clues, validate_board
from app.telemetry import instrument_app, tracer
from app.alerting import (
    IncidentAuthorizationError,
    InvalidWorkflowIdentity,
    MAX_BODY_BYTES,
    InvalidAlert,
    accept_incident,
    alert_lifespan,
    authorize_incident,
    validate_payload,
    verify_github_oidc_token,
)

settings = load_settings()
app = FastAPI(title="Simple Sudoku API", version="1.0.0", lifespan=alert_lifespan)
logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address, default_limits=[])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
password_hasher = PasswordHash.recommended()
csrf_signer = URLSafeSerializer(settings.session_secret.get_secret_value(), salt="sudoku-csrf-v1")
session_signer = URLSafeSerializer(settings.session_secret.get_secret_value(), salt="sudoku-session-v1")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,14}$", re.ASCII)
SESSION_COOKIE = "sudoku_session"
CSRF_COOKIE = "sudoku_csrf"
DUMMY_PASSWORD_HASH = password_hasher.hash("not-a-real-user-password")


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(RequestBody):
    username: StrictStr
    password: StrictStr


class BoardRequest(RequestBody):
    board: list[list[StrictInt | None]]


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError):
    # FastAPI's default validation response includes rejected input, potentially
    # including credentials. Never echo request bodies or validation contexts.
    return JSONResponse({"detail": "Invalid request data."}, status_code=422)


def _csrf_token() -> str:
    return csrf_signer.dumps(secrets.token_urlsafe(32))


def _csrf_valid(request: Request) -> bool:
    token = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("x-csrf-token")
    if not token or not header or not secrets.compare_digest(token, header):
        return False
    try:
        csrf_signer.loads(token)
        return True
    except BadSignature:
        return False


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    alert_routes = {
        "/api/alerts/grafana",
        "/api/alerts/repair/claim",
    }
    alert_route = request.method == "POST" and request.url.path in alert_routes
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/")
        and not alert_route
    ):
        if not _csrf_valid(request):
            return JSONResponse({"detail": "CSRF validation failed."}, status_code=403)
    return await call_next(request)


# Keep request observation outside CSRF middleware so even rejected requests
# produce the same bounded 4xx telemetry as other authentication failures.
instrument_app(app)


def current_player(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Player:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        session_signer.loads(raw_token)
    except BadSignature:
        raise HTTPException(status_code=401, detail="Authentication required.") from None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash, AuthSession.revoked.is_(False))
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    player = db.get(Player, session.player_id)
    if player is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return player


PlayerDependency = Annotated[Player, Depends(current_player)]
DatabaseDependency = Annotated[Session, Depends(get_db)]


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _new_session(db: Session, player: Player, response: Response) -> None:
    raw_token = session_signer.dumps(secrets.token_urlsafe(32))
    db.add(
        AuthSession(
            player_id=player.id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        )
    )
    db.commit()
    _set_session_cookie(response, raw_token)
    _set_csrf_cookie(response, _csrf_token())


def _validated_board(raw_board: object, clues: list[list[int | None]]) -> list[list[int | None]]:
    try:
        board = validate_board(raw_board)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if not preserves_clues(board, clues):
        raise HTTPException(status_code=422, detail="Original puzzle clues cannot be changed.")
    return board


def _owned_game(db: Session, game_id: int, player_id: int, *, lock: bool = False) -> Game:
    query = select(Game).where(Game.id == game_id, Game.player_id == player_id)
    if lock:
        query = query.with_for_update()
    game = db.scalar(query)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found.")
    return game


@app.get("/api/health")
def health(db: DatabaseDependency):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/alerts/grafana", status_code=202)
@limiter.limit("20/minute")
async def receive_grafana_alert(request: Request, db: DatabaseDependency):
    """Durably accept one supported development save-5xx firing notification."""
    if not settings.alert_repair_enabled or settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Alert receiver is unavailable.")
    if settings.alert_receiver_token is None or settings.alert_dispatch_token is None:
        raise HTTPException(status_code=503, detail="Alert receiver is not configured.")
    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {settings.alert_receiver_token.get_secret_value()}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Alert authentication failed.")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) < 0 or int(length) > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Alert payload is too large.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid alert request.") from None
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Alert payload is too large.")
        chunks.extend(chunk)
    try:
        payload = json.loads(chunks)
        incident_id = validate_payload(payload, development=True)
    except (json.JSONDecodeError, UnicodeDecodeError, InvalidAlert):
        raise HTTPException(status_code=422, detail="Unsupported alert payload.") from None
    try:
        created = accept_incident(db, incident_id)
    except OverflowError:
        raise HTTPException(status_code=429, detail="Alert intake limit reached.") from None
    except Exception as error:
        db.rollback()
        # Type only: DB diagnostics can contain parameters and sensitive state.
        import logging
        logging.getLogger(__name__).warning(
            "Alert intake failed (%s).", type(error).__name__
        )
        raise HTTPException(status_code=503, detail="Alert could not be durably accepted.") from None
    return {"accepted": True, "duplicate": not created}


class RepairClaimRequest(RequestBody):
    incident_id: str
    expires_at: str
    action: Literal["claim", "verify"]


@app.post("/api/alerts/repair/claim")
@limiter.limit("10/minute")
async def claim_repair_execution(
    request: Request,
    db: DatabaseDependency,
):
    """Authorize one workflow attempt for one durable, unexpired incident."""
    if not settings.alert_repair_enabled or settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Repair authorization is unavailable.")
    if settings.alert_dispatch_token is None:
        raise HTTPException(status_code=503, detail="Repair authorization is not configured.")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) < 0 or int(length) > 1024:
                raise HTTPException(status_code=413, detail="Authorization request is too large.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid authorization request.") from None
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > 1024:
            raise HTTPException(status_code=413, detail="Authorization request is too large.")
        chunks.extend(chunk)
    try:
        body = RepairClaimRequest.model_validate_json(chunks)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid authorization request.") from None
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token:
        raise HTTPException(status_code=401, detail="Workflow authentication failed.")
    try:
        workflow_run = verify_github_oidc_token(token)
    except InvalidWorkflowIdentity:
        raise HTTPException(status_code=401, detail="Workflow authentication failed.") from None
    try:
        expiry = authorize_incident(
            db,
            body.incident_id,
            workflow_run,
            expected_expires_at=body.expires_at,
            claim=body.action == "claim",
        )
        db.commit()
    except IncidentAuthorizationError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Incident authorization was rejected.") from None
    except Exception:
        db.rollback()
        logger.warning("Repair authorization persistence failed.")
        raise HTTPException(status_code=503, detail="Repair authorization is unavailable.") from None
    return {
        "authorized": True,
        "expires_at": expiry.isoformat(),
        "incident_id": body.incident_id,
        "run_id": str(workflow_run.run_id),
        "run_attempt": str(workflow_run.run_attempt),
    }


@app.get("/api/auth/csrf")
def get_csrf(response: Response):
    token = _csrf_token()
    _set_csrf_cookie(response, token)
    return {"csrfToken": token}


@app.post("/api/auth/register", status_code=201)
def register(credentials: Credentials, response: Response, db: DatabaseDependency):
    if not USERNAME_PATTERN.fullmatch(credentials.username):
        raise HTTPException(status_code=422, detail="Username must be 1-14 ASCII letters, digits, or underscores.")
    if not 8 <= len(credentials.password) <= 14:
        raise HTTPException(status_code=422, detail="Password must be 8-14 characters.")
    player = Player(
        username=credentials.username,
        password_hash=password_hasher.hash(credentials.password),
    )
    db.add(player)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if db.scalar(select(Player.id).where(func.lower(Player.username) == credentials.username.lower())) is not None:
            raise HTTPException(status_code=409, detail="Username is already registered.") from None
        raise HTTPException(status_code=503, detail="Registration is temporarily unavailable.") from None
    db.refresh(player)
    _new_session(db, player, response)
    return {"id": player.id, "username": player.username}


@app.post("/api/auth/login")
@limiter.limit(settings.login_rate_limit)
def login(request: Request, credentials: Credentials, response: Response, db: DatabaseDependency):
    username = credentials.username
    player = (
        db.scalar(select(Player).where(func.lower(Player.username) == username.lower()))
        if USERNAME_PATTERN.fullmatch(username)
        else None
    )
    candidate_hash = player.password_hash if player else DUMMY_PASSWORD_HASH
    password_ok = (
        8 <= len(credentials.password) <= 14
        and password_hasher.verify(credentials.password, candidate_hash)
    )
    if player is None or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    _new_session(db, player, response)
    return {"id": player.id, "username": player.username}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: DatabaseDependency, player: PlayerDependency):
    raw_token = request.cookies.get(SESSION_COOKIE, "")
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if session:
        session.revoked = True
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=settings.secure_cookies, samesite="lax")
    return {"loggedOut": True}


@app.get("/api/me")
def me(player: PlayerDependency):
    return {"id": player.id, "username": player.username}


@app.get("/api/puzzles")
def list_puzzles(player: PlayerDependency, db: DatabaseDependency):
    puzzles = db.scalars(select(Puzzle).order_by(Puzzle.id)).all()
    games = {
        game.puzzle_id: game
        for game in db.scalars(select(Game).where(Game.player_id == player.id)).all()
    }
    return [
        {
            "id": puzzle.id,
            "title": puzzle.title,
            "clues": puzzle.clues,
            "status": games[puzzle.id].status if puzzle.id in games else "unstarted",
            "gameId": games[puzzle.id].id if puzzle.id in games else None,
        }
        for puzzle in puzzles
    ]


@app.post("/api/games/{puzzle_id}", status_code=200)
def start_game(
    puzzle_id: int, player: PlayerDependency, db: DatabaseDependency,
    body: RequestBody | None = None,
):
    puzzle = db.get(Puzzle, puzzle_id)
    if puzzle is None:
        raise HTTPException(status_code=404, detail="Puzzle not found.")
    statement = (
        insert(Game)
        .values(player_id=player.id, puzzle_id=puzzle.id, board=puzzle.clues, status="in_progress")
        .on_conflict_do_nothing(constraint="uq_games_player_puzzle")
    )
    db.execute(statement)
    db.commit()
    game = db.scalar(select(Game).where(Game.player_id == player.id, Game.puzzle_id == puzzle.id))
    return _game_response(game, puzzle)


def _game_response(game: Game, puzzle: Puzzle):
    return {
        "id": game.id,
        "puzzleId": puzzle.id,
        "title": puzzle.title,
        "clues": puzzle.clues,
        "board": game.board,
        "status": game.status,
        "createdAt": game.created_at,
        "lastSavedAt": game.last_saved_at,
        "completedAt": game.completed_at,
    }


@app.get("/api/games/{game_id}")
def get_game(game_id: int, player: PlayerDependency, db: DatabaseDependency):
    game = _owned_game(db, game_id, player.id)
    return _game_response(game, db.get(Puzzle, game.puzzle_id))


@app.put("/api/games/{game_id}")
def save_game(
    game_id: int,
    body: BoardRequest,
    player: PlayerDependency,
    db: DatabaseDependency,
):
    with tracer.start_as_current_span(
        "db.save_game",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.operation", "UPDATE")
        try:
            game = _owned_game(db, game_id, player.id, lock=True)
            if game.status == "completed":
                raise HTTPException(status_code=409, detail="Completed games are read-only.")
            puzzle = db.get(Puzzle, game.puzzle_id)
            game.board = _validated_board(body.board, puzzle.clues)
            game.last_saved_at = text("CURRENT_TIMESTAMP")
            db.commit()
            db.refresh(game)
        except HTTPException:
            raise
        except Exception as error:
            # Exception messages can contain SQL and bound parameters. Record
            # only the safe exception type and status, never its value/message.
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
    return _game_response(game, puzzle)


@app.post("/api/games/{game_id}/submit")
def submit_game(
    game_id: int,
    body: BoardRequest,
    player: PlayerDependency,
    db: DatabaseDependency,
):
    game = _owned_game(db, game_id, player.id, lock=True)
    puzzle = db.get(Puzzle, game.puzzle_id)
    board = _validated_board(body.board, puzzle.clues)
    if game.status == "completed":
        return {"result": "correct", "status": "completed"}
    if not is_complete(board):
        return {"result": "incomplete", "status": "in_progress"}
    if not is_valid_solution(board):
        return {"result": "incorrect", "status": "in_progress"}
    game.board = board
    game.status = "completed"
    game.completed_at = text("CURRENT_TIMESTAMP")
    game.last_saved_at = text("CURRENT_TIMESTAMP")
    db.commit()
    return {"result": "correct", "status": "completed"}
