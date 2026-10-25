import os
from pathlib import Path
import runpy
import secrets
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import psycopg

from test_configuration import load_app


ROOT = Path(__file__).resolve().parents[1]


def hosted_environment(**overrides):
    environment = {
        "APP_ENV": "production",
        "SECRET_KEY": secrets.token_hex(32),
        "DATABASE_URL": "postgresql://example.invalid/example?sslmode=require",
        "DEMO_ENABLED": "true",
        "DEMO_ONLY": "true",
    }
    environment.update(overrides)
    return environment


class ProductionConfigurationTests(unittest.TestCase):
    def test_local_workflow_stays_non_demo_and_debugging_is_off(self):
        app = load_app({"SECRET_KEY": secrets.token_hex(32), "FLASK_DEBUG": "1"})["app"]
        self.assertFalse(app.debug)
        self.assertFalse(app.config["SESSION_COOKIE_SECURE"])
        self.assertFalse(app.config["DEMO_ONLY"])
        self.assertEqual(app.test_client().get("/login").status_code, 200)

    def test_hosted_cookies_require_https_and_debug_flag_is_ignored(self):
        app = load_app(hosted_environment(FLASK_DEBUG="1"))["app"]
        self.assertFalse(app.debug)
        response = app.test_client().get("/", base_url="https://example.invalid")
        cookie = response.headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(attribute, cookie)

    def test_production_cannot_enable_public_account_collection(self):
        for flags in ({"DEMO_ONLY": "false"}, {"DEMO_ENABLED": "false", "DEMO_ONLY": "false"}):
            with self.subTest(flags=flags), self.assertRaisesRegex(RuntimeError, "Public hosting"):
                load_app(hosted_environment(**flags))

    def test_bad_environment_and_short_production_key_are_rejected(self):
        for settings, message in (({"APP_ENV": "prod"}, "APP_ENV"), ({"SECRET_KEY": "short"}, "SECRET_KEY")):
            with self.subTest(settings=settings), self.assertRaisesRegex(RuntimeError, message):
                load_app(hosted_environment(**settings))

    def test_production_requires_encrypted_database_connection(self):
        for url in ("", "postgresql://example.invalid/example", "postgresql://example.invalid/example?sslmode=disable"):
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, "TLS"):
                load_app(hosted_environment(DATABASE_URL=url))
        for mode in ("require", "verify-ca", "verify-full"):
            app = load_app(hosted_environment(DATABASE_URL="postgresql://example.invalid/example?sslmode=" + mode))["app"]
            self.assertIn("sslmode=" + mode, app.config["DATABASE_URL"])

    def test_invalid_connection_configuration_does_not_echo_credentials(self):
        private_value = secrets.token_hex(24)
        with self.assertRaises(RuntimeError) as error:
            load_app(hosted_environment(DATABASE_URL="private_password=" + private_value))
        self.assertNotIn(private_value, str(error.exception))

    def test_health_does_not_open_database_or_change_demo_cookie(self):
        app = load_app(hosted_environment())["app"]
        client = app.test_client()
        with client.session_transaction(base_url="https://example.invalid") as session:
            session["demo_workspace"] = "expired-or-unavailable"
            session["demo_csrf"] = "existing-form-token"
        with patch("psycopg.connect", side_effect=AssertionError("Health check touched database")):
            response = client.get("/health", base_url="https://example.invalid")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        self.assertNotIn("Set-Cookie", response.headers)

    def test_oversized_demo_form_is_rejected_before_database_access(self):
        app = load_app(hosted_environment())["app"]
        client = app.test_client()
        client.get("/", base_url="https://example.invalid")
        with client.session_transaction(base_url="https://example.invalid") as session:
            token = session["demo_csrf"]
        with patch("psycopg.connect", side_effect=AssertionError("Oversized form touched database")):
            response = client.post("/demo/start/student", base_url="https://example.invalid",
                                   data={"demo_csrf": token, "extra": "x" * 65536})
        self.assertEqual(response.status_code, 413)


class ProductionStartupTests(unittest.TestCase):
    def start(self, app, initialize, environment=None):
        # Test startup guards without binding a port; real HTTP startup is
        # exercised separately against a disposable database before release.
        with patch("waitress.serve") as server:
            module = runpy.run_path(str(ROOT / "serve.py"))
            with patch.dict(sys.modules, {"app": SimpleNamespace(app=app, initialize_database=initialize)}), \
                    patch.dict(os.environ, environment or {}, clear=True):
                module["main"]()
        return server

    def test_startup_initializes_database_and_uses_provider_port(self):
        app = load_app(hosted_environment())["app"]
        initialize = Mock()
        server = self.start(app, initialize, {"PORT": "12345"})
        initialize.assert_called_once_with()
        server.assert_called_once_with(app, host="0.0.0.0", port=12345, threads=4,
                                       max_request_body_size=65536, expose_tracebacks=False)
        self.assertFalse(app.debug)

    def test_invalid_ports_never_start_server(self):
        app = load_app(hosted_environment())["app"]
        for port in ("", "bad", "0", "65536"):
            initialize = Mock()
            with self.subTest(port=port), self.assertRaisesRegex(SystemExit, "PORT"):
                self.start(app, initialize, {"PORT": port})
            initialize.assert_not_called()

    def test_local_settings_cannot_accidentally_start_hosted_server(self):
        app = load_app({"SECRET_KEY": secrets.token_hex(32)})["app"]
        initialize = Mock()
        with self.assertRaisesRegex(SystemExit, "APP_ENV=production"):
            self.start(app, initialize)
        initialize.assert_not_called()

    def test_database_startup_failure_is_safe_and_does_not_serve(self):
        app = load_app(hosted_environment())["app"]
        private_value = secrets.token_hex(24)
        with patch("waitress.serve") as server:
            module = runpy.run_path(str(ROOT / "serve.py"))
            initialize = Mock(side_effect=psycopg.OperationalError(private_value))
            with patch.dict(sys.modules, {"app": SimpleNamespace(app=app, initialize_database=initialize)}):
                with self.assertRaises(SystemExit) as error:
                    module["main"]()
            server.assert_not_called()
        self.assertNotIn(private_value, str(error.exception))
        self.assertIn("Database startup failed", str(error.exception))


if __name__ == "__main__":
    unittest.main()
