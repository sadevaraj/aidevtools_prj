"""Three fixed easy puzzles. The solution grids are generated from a valid pattern."""

SOLUTION = [
    [5, 3, 4, 6, 7, 8, 9, 1, 2],
    [6, 7, 2, 1, 9, 5, 3, 4, 8],
    [1, 9, 8, 3, 4, 2, 5, 6, 7],
    [8, 5, 9, 7, 6, 1, 4, 2, 3],
    [4, 2, 6, 8, 5, 3, 7, 9, 1],
    [7, 1, 3, 9, 2, 4, 8, 5, 6],
    [9, 6, 1, 5, 3, 7, 2, 8, 4],
    [2, 8, 7, 4, 1, 9, 6, 3, 5],
    [3, 4, 5, 2, 8, 6, 1, 7, 9],
]


def _puzzle(seed: int, title: str, offset: int) -> dict:
    solution = [[(value - 1 + offset) % 9 + 1 for value in row] for row in SOLUTION]
    clues = [[value if (r * 3 + c * 5 + seed * 7) % 9 >= 3 else None for c, value in enumerate(row)]
             for r, row in enumerate(solution)]
    return {"id": seed, "title": title, "clues": clues, "solution": solution}


PUZZLES = [
    _puzzle(1, "Morning Garden", 0),
    _puzzle(2, "Quiet Library", 3),
    _puzzle(3, "Coastal Walk", 6),
]
