"""Explicit, sanitized runtime configuration."""

from typing import Literal
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from limits import parse


class Settings(BaseSettings):
    """Runtime settings supplied by the process environment."""

    model_config = SettingsConfigDict(extra="ignore")

    app_env: Literal["development", "production"] = Field(validation_alias="APP_ENV")
    database_host: str = Field(validation_alias="DATABASE_HOST")
    database_port: int = Field(validation_alias="DATABASE_PORT", ge=1, le=65535)
    database_name: str = Field(validation_alias="DATABASE_NAME")
    database_user: str = Field(validation_alias="DATABASE_USER")
    database_password: SecretStr = Field(validation_alias="DATABASE_PASSWORD")
    session_secret: SecretStr = Field(validation_alias="SESSION_SECRET")
    login_rate_limit: str = Field(default="5/minute", validation_alias="LOGIN_RATE_LIMIT")

    @property
    def secure_cookies(self) -> bool:
        return self.app_env == "production"

    @field_validator("database_host", "database_name", "database_user")
    @classmethod
    def require_nonblank_setting(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("database_password")
    @classmethod
    def require_database_password(cls, value: SecretStr) -> SecretStr:
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
        return Settings()
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
        if "session_secret" in invalid_fields:
            messages.append("SESSION_SECRET must contain at least 32 characters")
        if "login_rate_limit" in invalid_fields:
            messages.append("LOGIN_RATE_LIMIT must use a count/period value")
        if not messages:
            messages.append("one or more environment settings are invalid")
        raise RuntimeError(f"Invalid configuration: {'; '.join(messages)}.") from None
