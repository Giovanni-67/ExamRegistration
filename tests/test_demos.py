"""Verify real demo workspaces without using private configuration or real records."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest

import psycopg
from psycopg import sql

import demo
import test_postgresql as pg


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL for PostgreSQL integration tests")
class RecruiterDemoTests(pg.PostgreSQLFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app.config.update(DEMO_ENABLED=True, DEMO_ONLY=False, DEMO_MAX_WORKSPACES=20)

    def tearDown(self):
        with self.connect() as conn:
            for workspace in conn.execute("SELECT id FROM demo_workspaces").fetchall():
                demo.delete_workspace(conn, workspace["id"])

    def token(self, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            return session["demo_csrf"]

    def start(self, role="student", client=None):
        client = client or self.client
        client.get("/")
        return client.post(f"/demo/start/{role}", data={"demo_csrf": self.token(client)})

    def post(self, path, data=None, client=None, follow=False):
        client = client or self.client
        return client.post(path, data={**(data or {}), "demo_csrf": self.token(client)}, follow_redirects=follow)

    def workspace(self, client=None):
        with (client or self.client).session_transaction() as session:
            workspace_id = session["demo_workspace"]
        with self.connect() as conn:
            return demo.find_workspace(conn, workspace_id)

    def demo_conn(self, client=None):
        conn = self.connect()
        demo.bind_workspace(conn, self.workspace(client)["id"])
        return conn

    def test_demo_entry_works_for_both_roles_and_is_disabled_by_default(self):
        self.app.config["DEMO_ENABLED"] = False
        self.assertNotIn(b"Try Student Demo", self.client.get("/").data)
        self.client.get("/")
        # No entry token exists on the disabled page; a forced POST is rejected.
        self.assertEqual(self.client.post("/demo/start/student").status_code, 403)
        self.app.config["DEMO_ENABLED"] = True
        home = self.client.get("/")
        self.assertIn(b"Try Student Demo", home.data)
        self.assertEqual(home.headers["Cache-Control"], "no-store")
        self.assertTrue(self.start().location.endswith("/student"))
        response = self.client.get("/student")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn(b"Fictional data", response.data)
        self.assertIn(b"DEMO-CS101", response.data)
        other = self.app.test_client()
        self.assertTrue(self.start("faculty", other).location.endswith("/faculty"))

    def test_missing_resource_does_not_clear_demo_entry_form_token(self):
        self.app.config["DEMO_ONLY"] = True
        self.client.get("/")
        token = self.token()
        self.assertEqual(self.client.get("/favicon.ico").status_code, 404)
        self.assertEqual(self.token(), token)
        response = self.client.post("/demo/start/student", data={"demo_csrf": token})
        self.assertTrue(response.location.endswith("/student"))

    def test_role_switch_preserves_workspace_and_student_bookings(self):
        self.start()
        original = self.workspace()["id"]
        self.post("/student/make-appointment", {"session_id": 2})
        self.post("/demo/start/faculty")
        self.assertEqual(self.workspace()["id"], original)
        self.assertIn(b"DEMO-MATH120", self.client.get("/faculty").data)
        self.post("/demo/start/student")
        self.assertIn(b"DEMO-MATH120", self.client.get("/student").data)

    def test_visitors_and_regular_accounts_have_separate_records(self):
        self.start("faculty")
        other = self.app.test_client()
        self.start("faculty", other)
        first = self.workspace()
        second = self.workspace(other)
        self.assertNotEqual(first["schema_name"], second["schema_name"])
        with self.demo_conn() as conn:
            conn.execute("UPDATE exams SET exam_code='ONLY-VISITOR-A' WHERE id=1")
        self.assertIn(b"ONLY-VISITOR-A", self.client.get("/faculty").data)
        self.assertNotIn(b"ONLY-VISITOR-A", other.get("/faculty").data)
        # Demo faculty cannot see or modify the application's normal accounts/tables.
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"], 2)
            self.assertEqual(conn.execute("SELECT exam_code FROM exams").fetchone()["exam_code"], "TEST-101")

    def test_tampered_ids_cannot_book_another_visitors_session(self):
        self.start("faculty")
        self.post("/faculty/sessions/new", {
            "exam_id": 1, "location_id": 1, "date": "2099-01-01", "time": "14:00", "capacity": 5,
        })
        other = self.app.test_client()
        self.start(client=other)
        response = self.post("/student/make-appointment", {"session_id": 6}, other, follow=True)
        self.assertIn(b"no longer exists", response.data)
        with self.demo_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM registrations WHERE session_id=6").fetchone()["n"], 0)

    def test_cancellation_does_not_change_another_visitors_matching_id(self):
        self.start()
        other = self.app.test_client()
        self.start(client=other)
        self.post("/student/cancel/1")
        with self.demo_conn() as conn:
            self.assertTrue(conn.execute("SELECT cancelled FROM registrations WHERE id=1").fetchone()["cancelled"])
        with self.demo_conn(other) as conn:
            self.assertFalse(conn.execute("SELECT cancelled FROM registrations WHERE id=1").fetchone()["cancelled"])

    def test_all_demo_writes_reject_missing_or_wrong_csrf(self):
        self.client.get("/")
        self.assertEqual(self.client.post("/demo/start/student", data={"demo_csrf": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post("/demo/start/student", data={"demo_csrf": "\u00e9"}).status_code, 403)
        self.start()
        for path in ("/demo/reset", "/demo/exit", "/demo/start/faculty", "/student/make-appointment", "/student/cancel/1"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 403)
        self.assertEqual(self.post("/demo/start/admin").status_code, 404)

    def test_demo_accounts_cannot_collect_signup_information(self):
        self.start()
        response = self.post("/signup", {"email": "do-not-store@example.invalid"})
        self.assertTrue(response.location.endswith("/student"))
        with self.demo_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"], 3)
        self.app.config["DEMO_ONLY"] = True
        anonymous = self.app.test_client()
        self.assertNotIn(b">Sign Up<", anonymous.get("/").data)
        self.assertTrue(anonymous.post("/signup", data={"email": "do-not-store@example.invalid"}).location.endswith("/"))

    def test_reset_replaces_only_the_current_workspace(self):
        self.start()
        old = self.workspace()
        other = self.app.test_client()
        self.start(client=other)
        other_id = self.workspace(other)["id"]
        self.post("/student/cancel/1")
        self.post("/demo/reset")
        self.assertNotEqual(self.workspace()["id"], old["id"])
        self.assertEqual(self.workspace(other)["id"], other_id)
        with self.connect() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (old["schema_name"],)).fetchone())
        with self.demo_conn() as conn:
            self.assertFalse(conn.execute("SELECT cancelled FROM registrations WHERE id=1").fetchone()["cancelled"])

    def test_failed_reset_rolls_back_and_preserves_existing_workspace(self):
        self.start()
        old = self.workspace()["id"]
        with self.connect() as conn:
            conn.execute("""CREATE FUNCTION reject_demo_insert() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'Test directory write failure'; END $$""")
            conn.execute("CREATE TRIGGER reject_demo_insert BEFORE INSERT ON demo_workspaces FOR EACH ROW EXECUTE FUNCTION reject_demo_insert()")
        try:
            self.post("/demo/reset")
        finally:
            with self.connect() as conn:
                conn.execute("DROP TRIGGER reject_demo_insert ON demo_workspaces")
                conn.execute("DROP FUNCTION reject_demo_insert()")
        self.assertEqual(self.workspace()["id"], old)
        self.assertEqual(self.client.get("/student").status_code, 200)

    def test_expiration_clears_session_and_cleanup_preserves_regular_data(self):
        self.start()
        old = self.workspace()
        with self.connect() as conn:
            conn.execute("UPDATE demo_workspaces SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' WHERE id=%s", (old["id"],))
        response = self.client.get("/student", follow_redirects=True)
        self.assertIn(b"demo has expired", response.data)
        result = self.app.test_cli_runner().invoke(args=["cleanup-demos"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Removed 1", result.output)
        with self.connect() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (old["schema_name"],)).fetchone())
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"], 2)

    def test_capacity_limit_and_expired_slot_reuse(self):
        self.app.config["DEMO_MAX_WORKSPACES"] = 1
        self.start()
        second = self.app.test_client()
        self.start(client=second)
        self.assertIn(b"currently in use", second.get("/").data)
        old = self.workspace()
        with self.connect() as conn:
            conn.execute("UPDATE demo_workspaces SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second'")
        self.start(client=second)
        self.assertNotEqual(self.workspace(second)["id"], old["id"])

    def test_simultaneous_starts_cannot_exceed_workspace_cap(self):
        self.app.config["DEMO_MAX_WORKSPACES"] = 1
        barrier = Barrier(2)

        def start_one(_):
            client = self.app.test_client()
            client.get("/")
            barrier.wait(timeout=10)
            return client.post("/demo/start/student", data={"demo_csrf": self.token(client)}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(start_one, range(2))), [302, 302])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM demo_workspaces").fetchone()["n"], 1)

    def test_exit_removes_workspace_and_regular_login_stays_available(self):
        self.start()
        old = self.workspace()
        self.assertTrue(self.post("/demo/exit").location.endswith("/"))
        with self.connect() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (old["schema_name"],)).fetchone())
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_invalid_workspace_marker_never_falls_back_to_regular_tables(self):
        self.start()
        with self.client.session_transaction() as session:
            session["demo_workspace"] = "not-a-workspace"
        response = self.client.get("/student", follow_redirects=True)
        self.assertIn(b"demo has expired", response.data)
        self.assertNotIn(b"TEST-101", response.data)

    def test_schema_names_are_not_accepted_as_sql(self):
        for name in ("public", "examreg_demo_x; DROP SCHEMA public CASCADE", "examreg_test_123"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                demo.checked_schema(name)

    def test_missing_demo_table_cannot_read_regular_table_with_same_name(self):
        self.start()
        with self.demo_conn() as conn:
            conn.execute("DROP TABLE exams CASCADE")
        with self.assertRaises(psycopg.errors.UndefinedTable), self.demo_conn() as conn:
            conn.execute("SELECT exam_code FROM exams")

    def test_cleanup_skips_workspaces_with_requests_in_flight(self):
        self.start()
        workspace = self.workspace()
        with self.connect() as conn:
            conn.execute("UPDATE demo_workspaces SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second'")
        with self.connect() as active_request:
            active_request.execute("SELECT id FROM demo_workspaces WHERE id=%s FOR SHARE", (workspace["id"],))
            with self.connect() as cleanup:
                self.assertEqual(demo.cleanup_expired(cleanup), 0)
        with self.connect() as cleanup:
            self.assertEqual(demo.cleanup_expired(cleanup), 1)

    def test_created_session_preserves_duration_and_rejects_bad_input(self):
        self.start("faculty")
        valid = {"exam_id": 1, "location_id": 1, "date": "2099-01-01", "time": "14:00", "capacity": 5, "duration_minutes": 120}
        self.post("/faculty/sessions/new", valid)
        with self.demo_conn() as conn:
            self.assertEqual(conn.execute("SELECT duration_minutes FROM examsessions WHERE id=6").fetchone()["duration_minutes"], 120)
        response = self.post("/faculty/sessions/new", {**valid, "capacity": "bad"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"positive capacity", response.data)

    def test_session_growth_is_bounded_inside_demo(self):
        self.start("faculty")
        with self.demo_conn() as conn:
            conn.execute("""INSERT INTO examsessions (exam_id,location_id,creator_id,proctor_id,session_datetime)
                SELECT 1,1,1,1,LOCALTIMESTAMP + INTERVAL '1 day' FROM generate_series(1,45)""")
        self.post("/faculty/sessions/new", {"exam_id": 1, "location_id": 1, "date": "2099-01-01", "time": "14:00", "capacity": 5})
        with self.demo_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM examsessions").fetchone()["n"], 50)


if __name__ == "__main__":
    unittest.main()
