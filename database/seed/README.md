# Database seed assets

The three fixed puzzle definitions and solutions are in
`backend/app/seed_data.py`; `python -m app.migrate` validates and inserts them
idempotently. Each seed is a valid 9×9 grid with 54 clues, derived from a
complete valid Sudoku pattern. Startup's backtracking counter stops after a
second solution and refuses to start unless each clue grid has exactly one.
The high clue count and balanced placement are the defensible easy-difficulty
rationale; no independent numerical difficulty scale is asserted.

The solution grids are stored for server-side puzzle validation, not returned
from the API. The player-facing board contains only clues and their own entries.
