"""Developer checks for required, sanitized backend configuration."""

import os
import secrets
import unittest
from unittest.mock import patch

from app.config import load_settings
from sqlalchemy.engine import URL


class SettingsTests(unittest.TestCase):
    def test_repair_defaults_off_without_obsolete_demo_controls(self):
        with patch.dict(os.environ, self.valid_env(), clear=True):
            settings = load_settings()
            self.assertFalse(settings.alert_repair_enabled)
            self.assertNotIn("demo_control_enabled", type(settings).model_fields)
            self.assertNotIn("demo_control_token", type(settings).model_fields)

    def valid_env(self):
        return {
            "APP_ENV": "development",
            "DATABASE_HOST": "database",
            "DATABASE_PORT": "5432",
            "DATABASE_NAME": "sudoku",
            "DATABASE_USER": "sudoku",
            "DATABASE_PASSWORD": secrets.token_hex(24),
            "SESSION_SECRET": secrets.token_hex(32),
        }

    def test_valid_development_configuration_loads(self) -> None:
        env = self.valid_env()
        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.app_env, "development")
        self.assertEqual(settings.database_host, "database")
        self.assertEqual(settings.database_port, 5432)
        self.assertEqual(settings.database_name, "sudoku")
        self.assertEqual(settings.database_user, "sudoku")
        self.assertNotIn(env["DATABASE_PASSWORD"], repr(settings))

    def test_development_database_url_works_without_split_settings(self) -> None:
        database_password = secrets.token_urlsafe(24)
        env = {
            "APP_ENV": "development",
            "DATABASE_URL": URL.create(
                "postgresql",
                username="url-user",
                password=database_password,
                host="url-db.example.test",
                database="url_database",
            ).render_as_string(hide_password=False),
            "SESSION_SECRET": secrets.token_hex(32),
        }
        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()
            from app.database import database_url_for_settings

            database_url = database_url_for_settings(settings)

        self.assertIsNotNone(settings.database_url)
        self.assertEqual(database_url.drivername, "postgresql+psycopg")
        self.assertEqual(database_url.host, "url-db.example.test")
        self.assertEqual(database_url.database, "url_database")
        self.assertNotIn(database_password, repr(settings))
        self.assertNotIn(
            database_password, database_url.render_as_string(hide_password=True)
        )

    def test_production_requires_database_url_and_accepts_render_url(self) -> None:
        env = self.valid_env()
        env["APP_ENV"] = "production"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL must be set"):
                load_settings()

        for key in ("DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD"):
            del env[key]
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL must be set"):
                load_settings()

        env["DATABASE_URL"] = "postgresql://render_user:test-only-password@localhost/sudoku"
        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.app_env, "production")
        self.assertEqual(settings.port, 8000)
        self.assertTrue(settings.secure_cookies)

    def test_invalid_development_database_url_is_rejected_without_leaking_value(self) -> None:
        private_password = secrets.token_urlsafe(24)
        env = {
            "APP_ENV": "development",
            "DATABASE_URL": f"postgresql://url-user:{private_password}@localhost",
            "SESSION_SECRET": secrets.token_hex(32),
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                load_settings()
        self.assertIn("DATABASE_URL", str(raised.exception))
        self.assertNotIn(env["DATABASE_URL"], str(raised.exception))
        self.assertNotIn(private_password, str(raised.exception))

    def test_invalid_database_url_diagnostic_does_not_leak_value(self) -> None:
        env = self.valid_env()
        env["APP_ENV"] = "production"
        del env["DATABASE_HOST"]
        secret_url = "mysql://render_user:test-only-password@localhost/sudoku"
        env["DATABASE_URL"] = secret_url
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                load_settings()
        self.assertIn("DATABASE_URL", str(raised.exception))
        self.assertNotIn(secret_url, str(raised.exception))

    def test_missing_configuration_has_clear_diagnostic(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APP_ENV.*DATABASE_HOST"):
                load_settings()

    def test_invalid_settings_do_not_leak_values(self) -> None:
        env = self.valid_env()
        env["DATABASE_PORT"] = "not-a-port"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                load_settings()
        self.assertIn("DATABASE_PORT", str(raised.exception))
        self.assertNotIn(env["DATABASE_PASSWORD"], str(raised.exception))

    def test_invalid_environment_is_rejected(self) -> None:
        env = self.valid_env()
        env["APP_ENV"] = "invalid"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APP_ENV must be explicitly set"):
                load_settings()

    def test_short_session_secret_is_rejected_without_value_leak(self) -> None:
        secret = "short-secret"
        env = self.valid_env()
        env["SESSION_SECRET"] = secret
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                load_settings()
        self.assertIn("SESSION_SECRET", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))

    def test_production_enables_secure_cookies(self) -> None:
        env = self.valid_env()
        env["APP_ENV"] = "production"
        env["DATABASE_URL"] = "postgresql://render_user:test-only-password@localhost/sudoku"
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(load_settings().secure_cookies)

    def test_cookie_secure_can_be_disabled_for_local_http(self) -> None:
        env = self.valid_env()
        env["APP_ENV"] = "production"
        env["DATABASE_URL"] = "postgresql://render_user:test-only-password@localhost/sudoku"
        env["COOKIE_SECURE"] = "false"
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(load_settings().secure_cookies)

    def test_render_port_is_validated_and_defaults_for_local_runs(self) -> None:
        env = self.valid_env()
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_settings().port, 8000)
        env["PORT"] = "10000"
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_settings().port, 10000)
        env["PORT"] = "70000"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PORT"):
                load_settings()

    def test_malformed_rate_limit_fails_configuration(self) -> None:
        for value in ("bad/minute", "5/nonsense", "0/minute"):
            env = self.valid_env()
            env["LOGIN_RATE_LIMIT"] = value
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(RuntimeError, "LOGIN_RATE_LIMIT"):
                    load_settings()


if __name__ == "__main__":
    unittest.main()
