"""Developer checks for required, sanitized backend configuration."""

import os
import secrets
import unittest
from unittest.mock import patch

from app.config import load_settings


class SettingsTests(unittest.TestCase):
    def test_valid_development_configuration_loads(self) -> None:
        password = secrets.token_hex(24)
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "development",
                "DATABASE_HOST": "database",
                "DATABASE_PORT": "5432",
                "DATABASE_NAME": "sudoku",
                "DATABASE_USER": "sudoku",
                "DATABASE_PASSWORD": password,
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.app_env, "development")
        self.assertEqual(settings.database_host, "database")
        self.assertEqual(settings.database_port, 5432)
        self.assertEqual(settings.database_name, "sudoku")
        self.assertEqual(settings.database_user, "sudoku")
        self.assertNotIn(password, repr(settings))

    def test_missing_configuration_has_clear_diagnostic(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APP_ENV.*DATABASE_HOST"):
                load_settings()

    def test_invalid_settings_do_not_leak_values(self) -> None:
        password = secrets.token_hex(24)
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "development",
                "DATABASE_HOST": "database",
                "DATABASE_PORT": "not-a-port",
                "DATABASE_NAME": "sudoku",
                "DATABASE_USER": "sudoku",
                "DATABASE_PASSWORD": password,
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as raised:
                load_settings()

        self.assertIn("DATABASE_PORT", str(raised.exception))
        self.assertNotIn(password, str(raised.exception))

    def test_invalid_environment_is_rejected(self) -> None:
        password = secrets.token_hex(24)
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "DATABASE_HOST": "database",
                "DATABASE_PORT": "5432",
                "DATABASE_NAME": "sudoku",
                "DATABASE_USER": "sudoku",
                "DATABASE_PASSWORD": password,
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "APP_ENV must be explicitly set"):
                load_settings()


if __name__ == "__main__":
    unittest.main()
