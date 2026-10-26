"""Explicit, sanitized runtime configuration."""

import os
from typing import Literal
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from limits import parse
from sqlalchemy.exc import ArgumentError
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Runtime settings supplied by the process environment."""

    model_config = SettingsConfigDict(extra="ignore")

    app_env: Literal["development", "production"] = Field(validation_alias="APP_ENV")
    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    database_host: str | None = Field(default=None, validation_alias="DATABASE_HOST")
    database_port: int | None = Field(default=None, validation_alias="DATABASE_PORT", ge=1, le=65535)
    database_name: str | None = Field(default=None, validation_alias="DATABASE_NAME")
    database_user: str | None = Field(default=None, validation_alias="DATABASE_USER")
    database_password: SecretStr | None = Field(default=None, validation_alias="DATABASE_PASSWORD")
    port: int = Field(default=8000, validation_alias="PORT", ge=1, le=65535)
    cookie_secure: bool | None = Field(default=None, validation_alias="COOKIE_SECURE")
    session_secret: SecretStr = Field(validation_alias="SESSION_SECRET")
    login_rate_limit: str = Field(default="5/minute", validation_alias="LOGIN_RATE_LIMIT")

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env == "production"

    @field_validator("database_url")
    @classmethod
    def require_postgresql_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except (ArgumentError, TypeError, ValueError):
            raise ValueError("must be a valid PostgreSQL connection URL") from None
        if (
            url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
            or not url.username
            or not url.password
            or not url.host
            or not url.database
        ):
            raise ValueError("must be a valid PostgreSQL connection URL")
        return value

    @field_validator("database_host", "database_name", "database_user")
    @classmethod
    def require_nonblank_setting(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("database_password")
    @classmethod
    def require_database_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        if not value.get_secret_value():
            raise ValueError("must not be blank")
        return value

    @field_validator("session_secret")
    @classmethod
    def require_session_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("must contain at least 32 characters")
        return value

    @field_validator("login_rate_limit")
    @classmethod
    def require_login_rate_limit(cls, value: str) -> str:
        try:
            if parse(value).amount < 1:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("must be a valid positive count/period limit") from None
        return value


def load_settings() -> Settings:
    """Load settings without exposing values in startup diagnostics."""

    try:
        settings = Settings()
    except ValidationError as error:
        invalid_fields = {
            str(item["loc"][-1]).lower()
            for item in error.errors(include_input=False)
        }
        messages = []
        if "app_env" in invalid_fields:
            messages.append("APP_ENV must be explicitly set to 'development' or 'production'")
        database_fields = {
            "database_host",
            "database_port",
            "database_name",
            "database_user",
            "database_password",
        }
        if invalid_fields.intersection(database_fields):
            messages.append(
                "DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, DATABASE_USER, and "
                "DATABASE_PASSWORD must be set to valid local database settings"
            )
        elif "DATABASE_URL" not in os.environ and os.environ.get("APP_ENV") != "production":
            messages.append(
                "DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, DATABASE_USER, and "
                "DATABASE_PASSWORD must be set for development"
            )
        if os.environ.get("APP_ENV") == "production" and "DATABASE_URL" not in os.environ:
            messages.append("DATABASE_URL must be set to a valid PostgreSQL connection URL in production")
        if "session_secret" in invalid_fields:
            messages.append("SESSION_SECRET must contain at least 32 characters")
        if "database_url" in invalid_fields:
            messages.append("DATABASE_URL must be a valid PostgreSQL connection URL")
        if "port" in invalid_fields:
            messages.append("PORT must be an integer between 1 and 65535")
        if "cookie_secure" in invalid_fields:
            messages.append("COOKIE_SECURE must be a boolean value")
        if "login_rate_limit" in invalid_fields:
            messages.append("LOGIN_RATE_LIMIT must use a count/period value")
        if not messages:
            messages.append("one or more environment settings are invalid")
        raise RuntimeError(f"Invalid configuration: {'; '.join(messages)}.") from None
    if settings.app_env == "production":
        if settings.database_url is None:
            raise RuntimeError(
                "Invalid configuration: DATABASE_URL must be set to a valid "
                "PostgreSQL connection URL in production."
            )
    elif any(
        value is None
        for value in (
            settings.database_host,
            settings.database_port,
            settings.database_name,
            settings.database_user,
            settings.database_password,
        )
    ):
        raise RuntimeError(
            "Invalid configuration: DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, "
            "DATABASE_USER, and DATABASE_PASSWORD must be set for development."
        )
    return settings
