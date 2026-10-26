import pytest

from app.seed_data import PUZZLES
from app.sudoku import count_solutions, is_complete, is_valid_solution, validate_board


def test_seed_puzzles_are_valid_and_uniquely_solvable():
    assert len(PUZZLES) == 3
    for puzzle in PUZZLES:
        clues = validate_board(puzzle["clues"])
        solution = validate_board(puzzle["solution"])
        assert count_solutions(clues) == 1
        assert is_complete(solution)
        assert is_valid_solution(solution)
        assert all(
            clues[row][column] is None or clues[row][column] == solution[row][column]
            for row in range(9)
            for column in range(9)
        )


def test_board_validation_rejects_wrong_shape_values_and_boolean():
    with pytest.raises(ValueError):
        validate_board([[None] * 9] * 8)
    board = [[None] * 9 for _ in range(9)]
    board[0][0] = 10
    with pytest.raises(ValueError):
        validate_board(board)
    board[0][0] = True
    with pytest.raises(ValueError):
        validate_board(board)


def test_solution_checker_requires_complete_valid_groups():
    solution = PUZZLES[0]["solution"]
    assert is_valid_solution(solution)
    incomplete = [row[:] for row in solution]
    incomplete[0][0] = None
    assert not is_valid_solution(incomplete)
    incorrect = [row[:] for row in solution]
    incorrect[0][0], incorrect[0][1] = incorrect[0][1], incorrect[0][0]
    assert is_complete(incorrect)
    assert not is_valid_solution(incorrect)


def test_seed_uniqueness_with_independent_row_major_exhaustive_solver_and_easy_singles():
    # Deliberately independent of the production MRV counter and stored solutions.
    for puzzle in PUZZLES:
        board = [row[:] for row in puzzle["clues"]]
        def candidates(r, c):
            peers = board[r] + [board[i][c] for i in range(9)]
            peers += [board[i][j] for i in range(r // 3 * 3, r // 3 * 3 + 3)
                      for j in range(c // 3 * 3, c // 3 * 3 + 3)]
            return [v for v in range(1, 10) if v not in peers]
        def exhaustive(index=0):
            if index == 81:
                return 1
            r, c = divmod(index, 9)
            if board[r][c] is not None:
                return exhaustive(index + 1)
            count = 0
            for value in candidates(r, c):
                board[r][c] = value
                count += exhaustive(index + 1)
            board[r][c] = None
            return count
        assert exhaustive() == 1
        # A reproducible easy rationale: all blanks solved by naked singles,
        # without guesses, hints or a fabricated numerical difficulty threshold.
        while any(None in row for row in board):
            progress = False
            for r in range(9):
                for c in range(9):
                    if board[r][c] is None and len(options := candidates(r, c)) == 1:
                        board[r][c] = options[0]
                        progress = True
            assert progress
        assert board == puzzle["solution"]


def test_row_column_and_box_checks_are_each_required():
    # A Latin square satisfies rows and columns but violates 3x3 boxes.
    latin = [[(r + c) % 9 + 1 for c in range(9)] for r in range(9)]
    assert all(len(set(row)) == 9 for row in latin)
    assert not is_valid_solution(latin)
    rows_bad = [row[:] for row in PUZZLES[0]["solution"]]
    rows_bad[0][0], rows_bad[1][0] = rows_bad[1][0], rows_bad[0][0]
    assert not is_valid_solution(rows_bad)
    columns_bad = [row[:] for row in PUZZLES[0]["solution"]]
    columns_bad[0][0], columns_bad[0][1] = columns_bad[0][1], columns_bad[0][0]
    assert not is_valid_solution(columns_bad)
    assert count_solutions(columns_bad) == 0
