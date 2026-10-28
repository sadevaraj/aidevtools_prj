# Simple Sudoku Product Specification

This is the authoritative product specification. Changes to player-facing
behaviour require user agreement before implementation. Keep related GitHub
issues and acceptance criteria aligned with approved changes.

Operational issue #20 uses the separately approved
[simplified recovery replacement](issue-20-replacement.md), with attributed
2026-10-28T09:39:20Z user approval. It changes no SUD requirement, player data,
Sudoku rule or migration. The replacement supersedes operational demo/fault
controls and manual-only repair merge, not SUD-01 through SUD-14 below.

The [shared agent guard](../../.github/agents/guards/specification-changes.md)
defines required human approval evidence and independent review.
[GitHub enforcement status](../spec-governance.md) is tracked separately.

See the [project overview](../../README.md) and [delivery process](../process.md).

### Problem Description

Players want a straightforward way to play Sudoku, leave an unfinished puzzle,
and continue later, including from another browser, using a simple account.

Simple Sudoku is a full-stack web application where a player registers or logs in,
chooses an easy puzzle, fills in the missing numbers, saves progress, and submits
the completed board for checking. The backend stores player names and game
progress in a database so that saved games survive a page refresh or application
restart.

The first version focuses on a small, complete experience rather than puzzle
generation, advanced solving tools, or competitive play. It is a new project for
demonstrating the AI Dev Tools Zoomcamp development workflow.

### Product Specification

#### Scope and Confirmed Decisions

- A standard 9-by-9 Sudoku board, divided into nine 3-by-3 boxes.
- Players register with a unique username and password, then log in to access
  their own games. Usernames are 1-14 characters and passwords are 8-14 characters.
- Three predefined, verified easy puzzles; no puzzle generator.
- Desktop browsers only for the first version.
- Progress is saved using a manual Save button; there is no automatic saving.
- Each player has at most one game per puzzle. Unfinished games can be resumed;
  completed games are read-only and cannot be replayed.
- Players enter and clear numbers in cells that are not original clues.
- Correctness is checked when the player submits the completed board, not while
  entering individual numbers.
- A frontend, backend API, and persistent database form one connected application.
- Render is the intended deployment platform. The database arrangement remains
  to be confirmed, with no paid database preferred.

#### Player Identity and Basic Authentication

Players register with a unique username and password. An existing username
cannot be registered again; returning players log in instead. No email address
or external sign-in provider is required.

Usernames must contain 1-14 ASCII letters, numbers, or underscores and are
case-insensitive: `Player1` and `player1` identify the same account and cannot
be registered separately. Passwords are case-sensitive and must contain 8-14
characters, with no mandatory special-character rules.

The frontend and backend enforce these rules and reject invalid values rather
than silently truncating them. Passwords must not be silently trimmed, lowercased,
or otherwise transformed.

Passwords are stored only as salted, adaptive password hashes using an
established library, never as plaintext or reversible encryption. Passwords,
password hashes, and session tokens must not appear in logs or API responses.

Authentication uses server-validated sessions with HttpOnly cookies,
Secure in the deployed HTTPS environment, and an appropriate SameSite policy.
State-changing requests must be protected against CSRF. Logout invalidates the
session on the server, and invalid or revoked sessions require login again.
There is no time-based session expiry or inactivity timeout in the initial
version. A session remains valid until logout/revocation; closing the browser
must not be described as server-side logout. This increases the risk from a
stolen session token, so players should log out on shared devices.

The backend identifies the player from the authenticated session, not a
client-supplied username or player ID. Every game read, save, and submission
checks ownership. Players can resume their own saved games from another browser
after logging in.

Login failures use a generic invalid-credentials message. Repeated login
attempts are rate-limited. Established libraries must be used for password
hashing and session security rather than custom cryptographic mechanisms.

Password reset and recovery are not included in the first version. Registration
must make this limitation clear; forgotten passwords cannot be recovered through
the application.

#### Main Player Journey

1. Register with a username and password, or log in to an existing account.
2. Choose one of three easy puzzles. Resume it if already started; a completed
   puzzle can only be viewed, not played again.
3. Start a game with the original clues already filled in.
4. Enter or clear numbers in editable cells.
5. Save the unfinished game using the Save button. There is no automatic saving;
   changes made since the last successful save are not guaranteed to survive
   leaving or refreshing the page.
6. Return, log in if needed, and select an owned saved game to resume with its
   entries intact.
7. Fill every cell and submit the board.
8. Receive a clear correct/incorrect result. An incorrect submission remains
   editable; a correct submission is recorded as completed and becomes read-only.
   Completed games cannot be reopened for editing, reset, or restarted.

#### Functional Requirements and Acceptance Criteria

| ID | Requirement | Acceptance criteria |
|---|---|---|
| SUD-01 | Register an account | Usernames contain 1-14 ASCII letters, numbers, or underscores and are unique case-insensitively. Passwords are case-sensitive, 8-14 characters long, and do not require special characters. Both UI and backend reject invalid lengths/characters without truncation or password transformation. Duplicate usernames, including case variants, are rejected without overwriting an account. Only a password hash is persisted; passwords and authentication secrets are never returned or logged. |
| SUD-02 | Puzzle selection | The application lists exactly three predefined easy puzzles. Every published puzzle has valid clues and exactly one verified solution. |
| SUD-03 | Start or reopen a game | Selecting an unstarted puzzle while authenticated creates a persisted game owned by the signed-in player and displays the matching 9-by-9 board. Selecting a started puzzle reopens the existing game. At most one game exists per player per puzzle, including concurrent start requests; completed puzzles cannot create a replay. |
| SUD-04 | Edit the board | A player can enter digits 1-9 or clear an editable cell. Original clues cannot be changed. Invalid cell values are rejected by both the UI and backend. |
| SUD-05 | Save progress manually | The Save button stores the current entries in the database; edits are not automatically saved. The UI confirms success only after the backend accepts the save; failures are visible and do not silently discard the player's current entries. The UI makes the manual-save behaviour clear. |
| SUD-06 | Resume progress | After logging in, a player can select their saved games and reopen one with its original puzzle and saved entries intact after a page refresh, backend restart, or login from another browser. |
| SUD-07 | Submit a board | An incomplete board receives a clear incomplete-board message. A complete board is checked by the backend against the puzzle's Sudoku constraints. |
| SUD-08 | Handle an incorrect solution | A completed but incorrect board receives an incorrect-result message, remains editable, and is not recorded as completed. No automatic correctness feedback is given during cell entry. |
| SUD-09 | Record completion | A correct board preserves the original clues and contains digits 1-9 exactly once in every row, column, and 3-by-3 box. Its completed state is persisted and remains visible read-only when reopened. The completed game cannot be edited, reset, or restarted. |
| SUD-10 | Enforce rules on the backend | Direct API requests cannot change original clues, persist invalid board shapes or cell values, claim completion without server-side validation, or modify a completed game. |
| SUD-11 | Log in and out | Valid credentials establish a session with no time-based expiry or inactivity timeout in this version. Invalid credentials show a generic error. Logout invalidates the server-side session; logged-out, revoked, and invalid sessions cannot access game data. |
| SUD-12 | Isolate player data | A player can list, read, save, and submit only their own games. Attempts to access another player's game are rejected, including direct API requests with a different game or player ID. |
| SUD-13 | Protect authentication | Deployed session cookies are HttpOnly and Secure with an appropriate SameSite policy. State-changing requests have CSRF protection. Excessive login attempts are rate-limited, and authentication/authorization failure paths are covered by automated tests. |
| SUD-14 | Desktop interface | Registration, login, puzzle selection, board editing, saving, submission, and logout are usable in a desktop browser. Mobile-specific layouts and touch controls are not required for the first version. |

#### Data to Persist

- Player username, internal identifier, and password hash.
- Session records associated with a player, including revocation
  information; raw session tokens must not be stored.
- Predefined puzzle identifier and original clues.
- Game identifier, associated player, and puzzle.
- A database-enforced unique player/puzzle pair to prevent duplicate games.
- Current board entries.
- Game status: in progress or completed.
- Creation, last-save, and completion timestamps.

Internal player identifiers alone do not provide authentication or authorization.

#### Out of Scope for the First Version

- Email verification, password reset/recovery, social login, and persistent
  "remember me" sessions.
- Public player profiles and profile customization.
- Generated puzzles or difficulty levels beyond the predefined easy set.
- Real-time mistake highlighting.
- Hints, automatic solving, and pencil marks.
- Multiplayer, leaderboards, and competitive scoring.
- AI features inside the game.
- Timed scoring, achievements, or a completed-game history dashboard.
- Time-based session expiry and inactivity timeouts.
- Editing, resetting, or restarting completed games.
- Replaying a completed puzzle as a new game.
- Automatic saving and mobile-specific support.

#### Technical Implementation Details to Specify

The product choices above are agreed. The following belong in the implementation
plan and do not change the player-facing scope:

- Authentication libraries and login rate-limit thresholds.
- Technology stack, free database provider, and Render deployment configuration.
- Desktop browser test targets.
