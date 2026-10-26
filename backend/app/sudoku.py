"""Sudoku board validation and solution-counting helpers."""

from typing import Any

Board = list[list[int | None]]


def validate_board(value: Any) -> Board:
    if not isinstance(value, list) or len(value) != 9:
        raise ValueError("Board must contain exactly 9 rows.")
    normalized: Board = []
    for row in value:
        if not isinstance(row, list) or len(row) != 9:
            raise ValueError("Each row must contain exactly 9 cells.")
        if any(cell is not None and (type(cell) is not int or cell < 1 or cell > 9) for cell in row):
            raise ValueError("Cells must be digits 1-9 or null.")
        normalized.append(list(row))
    return normalized


def preserves_clues(board: Board, clues: Board) -> bool:
    return all(clues[r][c] is None or board[r][c] == clues[r][c] for r in range(9) for c in range(9))


def is_complete(board: Board) -> bool:
    return all(cell is not None for row in board for cell in row)


def is_valid_solution(board: Board) -> bool:
    if not is_complete(board):
        return False
    groups = list(board)
    groups.extend([[board[r][c] for r in range(9)] for c in range(9)])
    groups.extend(
        [board[r][c] for r in range(br, br + 3) for c in range(bc, bc + 3)]
        for br in (0, 3, 6)
        for bc in (0, 3, 6)
    )
    return all(set(group) == set(range(1, 10)) for group in groups)


def count_solutions(board: Board, limit: int = 2) -> int:
    """Count solutions up to limit; used to independently verify seeded puzzles."""
    validate_board(board)
    groups = list(board)
    groups.extend([[board[r][c] for r in range(9)] for c in range(9)])
    groups.extend(
        [board[r][c] for r in range(br, br + 3) for c in range(bc, bc + 3)]
        for br in (0, 3, 6) for bc in (0, 3, 6)
    )
    if any(len(values := [v for v in group if v is not None]) != len(set(values)) for group in groups):
        return 0
    candidate = [row[:] for row in board]
    solutions = 0

    def search() -> None:
        nonlocal solutions
        if solutions >= limit:
            return
        target: tuple[int, int] | None = None
        options: set[int] | None = None
        for r in range(9):
            for c in range(9):
                if candidate[r][c] is None:
                    used = set(candidate[r])
                    used.update(candidate[i][c] for i in range(9))
                    used.update(
                        candidate[i][j]
                        for i in range(r // 3 * 3, r // 3 * 3 + 3)
                        for j in range(c // 3 * 3, c // 3 * 3 + 3)
                    )
                    choices = set(range(1, 10)) - used
                    if options is None or len(choices) < len(options):
                        target, options = (r, c), choices
                    if len(choices) == 0:
                        return
        if target is None:
            solutions += 1
            return
        r, c = target
        for value in options or ():
            candidate[r][c] = value
            search()
            candidate[r][c] = None
            if solutions >= limit:
                return

    search()
    return solutions
