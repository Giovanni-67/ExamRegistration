import os
from pathlib import Path
import runpy
import secrets
import subprocess
import unittest
from unittest.mock import patch

from itsdangerous import BadSignature


ROOT = Path(__file__).resolve().parents[1]


def load_app(environment):
    # Ignore any developer's private .env so tests cannot use real credentials.
    with patch.dict(os.environ, environment, clear=True), patch("dotenv.load_dotenv"):
        return runpy.run_path(str(ROOT / "app.py"))


class SecretKeyTests(unittest.TestCase):
    def test_missing_empty_or_known_development_key_stops_startup(self):
        for value in (None, "", "   ", "dev-secret"):
            with self.subTest(value=value):
                environment = {} if value is None else {"SECRET_KEY": value}
                with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
                    load_app(environment)

    def test_configured_key_can_sign_sessions(self):
        key = secrets.token_hex(32)
        app = load_app({"SECRET_KEY": key})["app"]
        serializer = app.session_interface.get_signing_serializer(app)
        cookie = serializer.dumps({"user_id": 12, "role": "student"})
        self.assertEqual(serializer.loads(cookie)["user_id"], 12)

    def test_different_installations_reject_each_others_sessions(self):
        first = load_app({"SECRET_KEY": secrets.token_hex(32)})["app"]
        second = load_app({"SECRET_KEY": secrets.token_hex(32)})["app"]
        cookie = first.session_interface.get_signing_serializer(first).dumps(
            {"user_id": 12, "role": "faculty"}
        )
        with self.assertRaises(BadSignature):
            second.session_interface.get_signing_serializer(second).loads(cookie)

    def test_public_pages_work_without_opening_database_connections(self):
        with patch("psycopg.connect", side_effect=AssertionError("Unexpected DB access")):
            app = load_app({"SECRET_KEY": secrets.token_hex(32)})["app"]
            with app.test_client() as client:
                for path in ("/", "/login", "/signup"):
                    with self.subTest(path=path):
                        self.assertEqual(client.get(path).status_code, 200)

    def test_private_dotenv_still_supports_local_startup(self):
        from tempfile import TemporaryDirectory
        from dotenv import load_dotenv

        key = secrets.token_hex(32)
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("SECRET_KEY=" + key + "\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch(
                "dotenv.load_dotenv", side_effect=lambda **_: load_dotenv(env_file)
            ):
                app = runpy.run_path(str(ROOT / "app.py"))["app"]
                self.assertEqual(app.secret_key, key)

    def test_host_environment_takes_priority_over_dotenv(self):
        from tempfile import TemporaryDirectory
        from dotenv import load_dotenv

        hosted_key = secrets.token_hex(32)
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("SECRET_KEY=" + secrets.token_hex(32), encoding="utf-8")
            with patch.dict(os.environ, {"SECRET_KEY": hosted_key}, clear=True), patch(
                "dotenv.load_dotenv", side_effect=lambda **_: load_dotenv(env_file)
            ):
                app = runpy.run_path(str(ROOT / "app.py"))["app"]
                self.assertEqual(app.secret_key, hosted_key)


class DatabaseConfigurationTests(unittest.TestCase):
    def test_missing_database_url_has_a_safe_setup_error(self):
        module = load_app({"SECRET_KEY": secrets.token_hex(32)})
        with self.assertRaisesRegex(RuntimeError, "Set DATABASE_URL"):
            module["get_conn"]()

    def test_database_url_retains_provider_tls_settings(self):
        from psycopg.rows import dict_row

        url = "postgresql://example.invalid/example?sslmode=verify-full"
        module = load_app({"SECRET_KEY": secrets.token_hex(32), "DATABASE_URL": url})
        with patch("psycopg.connect") as connect:
            module["get_conn"]()
        connect.assert_called_once_with(url, row_factory=dict_row, connect_timeout=10)


class RepositoryHygieneTests(unittest.TestCase):
    def test_secret_files_are_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        )
        private_files = [
            path for path in result.stdout.split("\0") if path
            and Path(path).name != ".env.example"
            and (Path(path).name == ".env" or Path(path).name.startswith(".env."))
        ]
        self.assertEqual(private_files, [])

    def test_private_configuration_and_generated_files_are_ignored(self):
        for path in (".env", ".env.local", ".env.production", ".venv/file", "venv/file",
                     "__pycache__/app.pyc", "tests/__pycache__/test.pyc"):
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT,
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0)
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", ".env.example"], cwd=ROOT,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
