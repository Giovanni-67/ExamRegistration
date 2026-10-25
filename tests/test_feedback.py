from html.parser import HTMLParser
import secrets
import unittest
from unittest.mock import patch

from flask import abort
import psycopg

from test_configuration import load_app


class ThemeControls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.controls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "toggle-btn" in attributes.get("class", "").split():
            self.controls.append((tag, attributes))


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.app = load_app({"SECRET_KEY": secrets.token_hex(32),
                             "DATABASE_URL": "postgresql://example.invalid/example"})["app"]
        self.client = self.app.test_client()

    def test_public_theme_controls_are_named_native_buttons(self):
        for path in ("/", "/login", "/signup", "/page-that-does-not-exist"):
            with self.subTest(path=path):
                parser = ThemeControls()
                parser.feed(self.client.get(path).get_data(as_text=True))
                self.assertEqual(len(parser.controls), 1)
                tag, attributes = parser.controls[0]
                self.assertEqual(tag, "button")
                self.assertEqual(attributes.get("type"), "button")
                self.assertTrue(attributes.get("aria-label"))

    def test_missing_page_offers_recovery_without_creating_a_session(self):
        response = self.client.get("/page-that-does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Page not found", response.data)
        self.assertIn(b'href="/"', response.data)
        self.assertNotIn("Set-Cookie", response.headers)

    def test_validation_permission_and_size_errors_keep_status_codes(self):
        @self.app.route("/test-error/<int:status>")
        def test_error(status):
            abort(status)

        for status, message in ((400, b"Check the request"), (403, b"This action is not available"),
                                (413, b"This form is too large")):
            with self.subTest(status=status):
                response = self.client.get(f"/test-error/{status}")
                self.assertEqual(response.status_code, status)
                self.assertIn(message, response.data)
                self.assertIn(b"Return to home", response.data)

    def test_database_outage_is_not_reported_as_an_empty_result(self):
        self.app.config.update(DEMO_ENABLED=True, DEMO_ONLY=True)
        with self.client.session_transaction() as session:
            session["demo_workspace"] = "existing-visitor"
            session["demo_csrf"] = "existing-token"
        private_detail = secrets.token_hex(24)
        with patch("psycopg.connect", side_effect=psycopg.OperationalError(private_detail)):
            response = self.client.get("/student")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Temporarily unavailable", response.data)
        self.assertNotIn(private_detail.encode(), response.data)
        with self.client.session_transaction() as session:
            self.assertEqual(session["demo_workspace"], "existing-visitor")

    def test_unexpected_failure_does_not_show_debugging_details(self):
        self.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
        private_detail = secrets.token_hex(24)

        @self.app.route("/test-failure")
        def test_failure():
            raise ValueError(private_detail)

        with patch.object(self.app.logger, "error"):
            response = self.client.get("/test-failure")
        self.assertEqual(response.status_code, 500)
        self.assertIn(b"We could not finish that request", response.data)
        self.assertNotIn(private_detail.encode(), response.data)


if __name__ == "__main__":
    unittest.main()
