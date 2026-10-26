"""Apply schema migrations and deterministic puzzle seeds before serving."""

import os
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Puzzle
from app.seed_data import PUZZLES
from app.sudoku import count_solutions, is_valid_solution, validate_board


def main() -> None:
    config = Config(os.environ.get("ALEMBIC_CONFIG", "/app/alembic.ini"))
    command.upgrade(config, "head")
    with SessionLocal() as db, db.begin():
        for item in PUZZLES:
            clues = validate_board(item["clues"])
            solution = validate_board(item["solution"])
            if not is_valid_solution(solution) or count_solutions(clues) != 1 or not all(
                clues[r][c] is None or clues[r][c] == solution[r][c]
                for r in range(9) for c in range(9)
            ):
                raise RuntimeError(f"Puzzle seed {item['id']} failed uniqueness/solution validation")
            existing = db.get(Puzzle, item["id"])
            if existing is None:
                db.add(Puzzle(id=item["id"], title=item["title"], clues=clues, solution=solution))
            elif (existing.title, existing.clues, existing.solution) != (item["title"], clues, solution):
                raise RuntimeError(f"Puzzle seed {item['id']} differs from persisted data")
        db.flush()
        puzzle_count = len(db.scalars(select(Puzzle.id)).all())
        if puzzle_count != 3:
            raise RuntimeError(f"Expected exactly 3 puzzles; found {puzzle_count}")


if __name__ == "__main__":
    main()
