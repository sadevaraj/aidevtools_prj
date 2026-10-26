"""Developer checks for required, sanitized backend configuration."""

import os
import secrets
import unittest
from unittest.mock import patch

from app.config import load_settings


class SettingsTests(unittest.TestCase):
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
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(load_settings().secure_cookies)

    def test_malformed_rate_limit_fails_configuration(self) -> None:
        for value in ("bad/minute", "5/nonsense", "0/minute"):
            env = self.valid_env()
            env["LOGIN_RATE_LIMIT"] = value
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(RuntimeError, "LOGIN_RATE_LIMIT"):
                    load_settings()


if __name__ == "__main__":
    unittest.main()
