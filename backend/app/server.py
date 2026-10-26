"""Run the API on the port supplied by the hosting platform."""

import uvicorn

from app.main import app, settings


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
