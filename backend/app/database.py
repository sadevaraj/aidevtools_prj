"""PostgreSQL engine and request-scoped sessions."""

from collections.abc import Generator

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, load_settings


def database_url_for_settings(settings: Settings) -> URL:
    """Select the configured PostgreSQL URL, preferring DATABASE_URL."""
    if settings.database_url is not None:
        return make_url(settings.database_url.get_secret_value()).set(
            drivername="postgresql+psycopg"
        )

    # The split settings remain supported for the existing local-development
    # Compose stack and isolated integration tests.
    return URL.create(
        "postgresql+psycopg",
        username=settings.database_user,
        password=(
            settings.database_password.get_secret_value()
            if settings.database_password is not None
            else None
        ),
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
    )


settings = load_settings()
url = database_url_for_settings(settings)
engine = create_engine(url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
