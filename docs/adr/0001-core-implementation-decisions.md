# ADR-0001: Core authentication, routing, and verification choices

- **Status:** Accepted for the authorized core milestone; not deployment evidence.
- **Date:** 2026-10-26
- **Scope:** Issues #1 and #3–#10, as implemented in the current branch.
- **Product baseline:** `docs/specs/product.md` at base revision
  `8076770734222872446af8cf657e64d062cd987e`.

## Authorization

The owner explicitly delegated technical choices in the task instruction dated
2026-10-26:

> “Technical choices are explicitly delegated by the owner in current user
> request dated 2026-10-26, including established libraries, proxy, rate limits
> and test runner.”

The authorization and scope are also recorded in the agent-recorded issue
comment: [issue #1 work-start authorization](https://github.com/sadevaraj/aidevtools_prj/issues/1#issuecomment-6412741215).
This decision records implementation choices, not a change to player-facing
requirements.

## Decisions

### Passwords and sessions

- `pwdlib[argon2]` (`PasswordHash.recommended()`) provides salted adaptive
  Argon2 password hashing. The plaintext password is never transformed before
  hashing or verification.
- `itsdangerous.URLSafeSerializer` signs random opaque session cookie values and
  CSRF values. The session ID is random; PostgreSQL persists only its SHA-256
  lookup hash, player association, and revocation flag. Every authenticated
  request validates both the signed cookie and active database row. Logout
  revokes the row. No timed signer, cookie max-age, or inactivity expiry is
  used. The database—not the signature alone—is authoritative for revocation.
- The session cookie is HttpOnly, SameSite=Lax, and Secure when `APP_ENV` is
  `production` (required for any future HTTPS deployment, including development).
  The CSRF double-submit cookie is signed and paired with the
  `X-CSRF-Token` header on every state-changing `/api/` request, including
  registration, login, and logout.
- `slowapi` applies a configured default limit of **5 login attempts per
  minute per backend-observed source address**. `LOGIN_RATE_LIMIT` can set the
  value explicitly. Its default in-memory storage is suitable for this
  single-instance development milestone; multi-instance/distributed rate
  limiting remains an operational deployment decision.

### Frontend/API routing

The frontend Nginx server proxies `/api/` to the backend using the runtime
`API_UPSTREAM` value. Browser requests, including authentication, remain
same-origin; backend cookies are host-only cookies for the frontend origin.
This avoids dependence on third-party cookies or cross-origin CSRF behavior.
Compose verifies the proxy locally. A Render deployment must set
`API_UPSTREAM` to the backend service address; no remote service, cookie, or
Render behavior has been exercised here.

### Migrations, seeds, and tests

- Alembic migrations create PostgreSQL-backed players, case-insensitive
  username uniqueness, hashed/revocable sessions, puzzles, and games with a
  database unique player/puzzle pair.
- Startup validates and idempotently inserts the three fixed puzzles before
  launching the API. A bounded backtracking solution counter verifies that each
  seed has exactly one solution. A separate test exhaustively enumerates
  solutions using an independent row-major solver and verifies every puzzle can
  be solved using naked singles alone, without guessing. The 54-clue patterns
  are intentionally dense and balanced; no numerical difficulty standard is claimed.
- `sh scripts/test.sh` is the single root verification command. It uses
  isolated temporary PostgreSQL in Compose (tmpfs), Pytest for backend and
  database integration, and Vitest/Testing Library for frontend interactions,
  followed by the frontend type check and production build. Test cleanup removes
  only its uniquely named project.
- The declared desktop browser target is Chromium. Automated local browser
  verification is recorded in the DEV evidence only if the integrated browser
  successfully exercises the running Compose application. No other browser or
  deployed environment is assumed.

## Verification implications and limits

Tests verify cookie attributes, token redaction from persistence/responses,
CSRF rejection, generic login errors, rate limiting, ownership, concurrent
unique game start, clue immutability, manual-save-only browser behavior,
durable database reads, server completion checks, and completed-game mutation
rejection. Unit tests also verify seeded uniqueness and board validation.

The memory-backed rate limiter is process-local, and browser/manual results are
local-only. External ingress restrictions, Render environment variables,
multi-instance rate-limit storage, CI, and deployment remain outside this ADR's
verified scope.

Game writes acquire a PostgreSQL row lock: saves serialize and cannot overwrite
a completed game. There is no client revision/merge protocol; simultaneous
unfinished saves are serialized, with the last accepted save stored. The UI
disables editing/navigation during a write to avoid losing edits made while a
request is pending. Cross-tab conflict detection/merging is not claimed.
Rate limiting currently counts the backend-observed address; through the local
Nginx proxy this is a shared proxy address. This deliberately conservative local
limit must be revisited with trusted-proxy configuration before remote deployment.
