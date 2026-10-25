"""Real database tests. Set TEST_DATABASE_URL to a disposable PostgreSQL database.

Each run uses its own schema, never the application's regular tables or .env.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import secrets
from threading import Barrier
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from test_configuration import ROOT, load_app


class PostgreSQLFixture:
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ["TEST_DATABASE_URL"]
        cls.schema = "examreg_test_" + secrets.token_hex(8)
        with psycopg.connect(cls.base_url) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.database_url = make_conninfo(cls.base_url, options="-csearch_path=" + cls.schema)
        cls.module = load_app({"SECRET_KEY": secrets.token_hex(32), "DATABASE_URL": cls.database_url})
        cls.app = cls.module["app"]
        cls.app.config["TESTING"] = True
        cls.password = "1234567890"
        cls.password_hash = cls.module["bcrypt"].generate_password_hash(cls.password).decode()
        with cls.connect() as conn:
            conn.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))
            conn.execute((ROOT / "demo_registry.sql").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        # Only remove the uniquely named schema created by this test class.
        with psycopg.connect(cls.base_url) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    @classmethod
    def connect(cls):
        return psycopg.connect(cls.database_url, row_factory=dict_row)

    def setUp(self):
        with self.connect() as conn:
            conn.execute("TRUNCATE users, exams, locations, examsessions, registrations, appointments RESTART IDENTITY CASCADE")
            self.faculty = self.insert_user(conn, "teacher.one@csn.edu", "faculty")
            self.student = self.insert_user(conn, "0000000001@student.csn.edu", "student", "0000000001")
            self.exam = conn.execute(
                "INSERT INTO exams (exam_code, description) VALUES ('TEST-101', 'Fictional test exam') RETURNING id"
            ).fetchone()["id"]
            self.location = conn.execute(
                "INSERT INTO locations (campus_name, building_name, room_number) VALUES ('Henderson', 'Test Building', '101') RETURNING id"
            ).fetchone()["id"]
        self.client = self.app.test_client()

    def insert_user(self, conn, email, role, nshe=None):
        return conn.execute(
            "INSERT INTO users (email, role, nshe, full_name, password_hash) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (email, role, nshe, "Fictional Test User", self.password_hash),
        ).fetchone()["id"]

    def create_session(self, capacity=20, days=1):
        with self.connect() as conn:
            return conn.execute(
                """INSERT INTO examsessions (exam_id, location_id, creator_id, proctor_id, capacity, session_datetime)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (self.exam, self.location, self.faculty, self.faculty, capacity, datetime.now() + timedelta(days=days)),
            ).fetchone()["id"]

    def sign_in(self, user_id=None, role="student", client=None):
        with (client or self.client).session_transaction() as session:
            session["user_id"] = user_id or self.student
            session["role"] = role
            session["user_name"] = "Fictional Test User"

    def book(self, session_id, client=None):
        return (client or self.client).post("/student/make-appointment", data={"session_id": str(session_id)})

    def count_booked(self, session_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM registrations WHERE session_id=%s AND NOT cancelled", (session_id,)
            ).fetchone()["count"]

@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL for PostgreSQL integration tests")
class PostgreSQLTests(PostgreSQLFixture, unittest.TestCase):
    def test_schema_can_be_initialized_twice_without_losing_records(self):
        for _ in range(2):
            result = self.app.test_cli_runner().invoke(args=["init-db"])
            self.assertEqual(result.exit_code, 0, result.output)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM exams").fetchone()["count"], 1)

    def test_multiple_faculty_signup_and_login_with_no_student_id(self):
        for email in ("teacher.two@csn.edu", "teacher.three@csn.edu"):
            response = self.client.post("/signup", data={
                "full_name": "Fictional Faculty", "email": email, "role": "faculty",
                "password": self.password, "confirm": self.password,
            })
            self.assertTrue(response.location.endswith("/login"))
        response = self.client.post("/login", data={"email": "teacher.two@csn.edu", "password": self.password})
        self.assertTrue(response.location.endswith("/faculty"))
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM users WHERE nshe IS NULL").fetchone()["count"], 3)

    def test_duplicate_signup_does_not_break_later_requests(self):
        response = self.client.post("/signup", data={
            "full_name": "Fictional Student", "email": "0000000001@student.csn.edu", "role": "student",
            "password": self.password, "confirm": self.password,
        }, follow_redirects=True)
        self.assertIn(b"already registered", response.data)
        response = self.client.post("/login", data={"email": "0000000001@student.csn.edu", "password": self.password})
        self.assertTrue(response.location.endswith("/student"))

    def test_student_signup_and_invalid_login(self):
        self.client.post("/signup", data={
            "full_name": "Fictional Student", "email": "0000000002@student.csn.edu", "role": "student",
            "password": self.password, "confirm": self.password,
        })
        with self.connect() as conn:
            row = conn.execute("SELECT nshe FROM users WHERE email=%s", ("0000000002@student.csn.edu",)).fetchone()
            self.assertEqual(row["nshe"], "0000000002")
        response = self.client.post("/login", data={"email": "0000000002@student.csn.edu", "password": "wrong"}, follow_redirects=True)
        self.assertIn(b"Invalid email or password", response.data)

    def test_booking_dashboard_cancel_history_and_rebook(self):
        exam_session = self.create_session()
        self.sign_in()
        self.assertTrue(self.book(exam_session).location.endswith("/student/confirmation"))
        for path in ("/student", "/student/history", "/student/cancel-appointments", "/student/confirmation"):
            self.assertEqual(self.client.get(path).status_code, 200)
        with self.connect() as conn:
            registration = conn.execute("SELECT id FROM registrations").fetchone()["id"]
        self.client.post(f"/student/cancel/{registration}")
        self.assertEqual(self.count_booked(exam_session), 0)
        self.assertIn(b"Canceled", self.client.get("/student/history").data)
        self.book(exam_session)
        self.assertEqual(self.count_booked(exam_session), 1)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM registrations").fetchone()["count"], 1)

    def test_full_session_rejects_new_and_restored_bookings(self):
        exam_session = self.create_session(capacity=1)
        self.sign_in()
        self.book(exam_session)
        with self.connect() as conn:
            second_student = self.insert_user(conn, "0000000002@student.csn.edu", "student", "0000000002")
        self.sign_in(second_student)
        response = self.book(exam_session)
        self.assertIn(b"just filled up", self.client.get(response.location).data)
        with self.connect() as conn:
            conn.execute("INSERT INTO registrations (session_id,user_id,cancelled) VALUES (%s,%s,TRUE)", (exam_session, second_student))
        self.book(exam_session)
        self.assertEqual(self.count_booked(exam_session), 1)
        with self.connect() as conn:
            self.assertTrue(conn.execute("SELECT cancelled FROM registrations WHERE user_id=%s", (second_student,)).fetchone()["cancelled"])

    def test_duplicate_booking_is_idempotent(self):
        exam_session = self.create_session()
        self.sign_in()
        self.book(exam_session)
        self.book(exam_session)
        self.assertEqual(self.count_booked(exam_session), 1)

    def test_three_appointment_limit_and_invalid_or_past_sessions(self):
        self.sign_in()
        past = self.create_session(days=-1)
        self.assertNotIn(f'value="{past}"'.encode(), self.client.get("/student/make-appointment").data)
        for value in (past, 999999, "bad", "1' OR 1=1", "9" * 40, "0", "-1"):
            self.assertNotEqual(self.book(value).location, "/student/confirmation")
        for _ in range(3):
            self.book(self.create_session())
        fourth = self.create_session()
        self.assertTrue(self.book(fourth).location.endswith("/student"))
        self.assertEqual(self.count_booked(fourth), 0)

    def test_permissions_and_cancellation_ownership(self):
        self.assertTrue(self.client.get("/student/make-appointment").location.endswith("/login"))
        self.sign_in()
        self.assertEqual(self.client.get("/faculty").status_code, 403)
        exam_session = self.create_session()
        self.book(exam_session)
        with self.connect() as conn:
            registration = conn.execute("SELECT id FROM registrations").fetchone()["id"]
            second = self.insert_user(conn, "0000000002@student.csn.edu", "student", "0000000002")
        self.sign_in(second)
        self.client.post(f"/student/cancel/{registration}")
        self.assertEqual(self.count_booked(exam_session), 1)

    def test_faculty_creation_and_grouped_calendar_queries(self):
        self.sign_in(self.faculty, "faculty")
        self.assertEqual(self.client.get("/faculty/sessions/new").status_code, 200)
        future = datetime.now() + timedelta(days=1)
        response = self.client.post("/faculty/sessions/new", data={
            "exam_id": self.exam, "location_id": self.location, "capacity": 2,
            "date": future.strftime("%Y-%m-%d"), "time": "14:00",
        })
        self.assertTrue(response.location.endswith("/faculty"))
        self.assertIn(b"TEST-101", self.client.get(f"/faculty/{future.year}/{future.month}").data)
        rows = self.module["fetch_sessions_between"](datetime.now(), datetime.now() + timedelta(days=3))
        self.assertEqual(rows[0]["booked"], 0)

    def test_empty_database_pages(self):
        self.sign_in()
        for path in ("/student", "/student/history", "/student/cancel-appointments", "/student/make-appointment"):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_database_constraints_reject_invalid_session_values(self):
        for column, value in (("capacity", 0), ("duration_minutes", -1), ("exam_id", 999999)):
            with self.subTest(column=column):
                with self.assertRaises(psycopg.IntegrityError), self.connect() as conn:
                    conn.execute(
                        """INSERT INTO examsessions (exam_id,location_id,creator_id,proctor_id,session_datetime)
                           VALUES (%s,%s,%s,%s,LOCALTIMESTAMP)""",
                        (self.exam, self.location, self.faculty, self.faculty),
                    )
                    conn.execute(sql.SQL("UPDATE examsessions SET {} = %s").format(sql.Identifier(column)), (value,))

    def test_faculty_database_error_is_safe_and_does_not_block_next_request(self):
        self.sign_in(self.faculty, "faculty")
        response = self.client.post("/faculty/sessions/new", data={
            "exam_id": 999999, "location_id": self.location, "capacity": 2,
            "date": "2099-01-01", "time": "14:00",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"foreign key", response.data)
        self.assertEqual(self.client.get("/faculty").status_code, 200)

    def test_failed_booking_transaction_rolls_back(self):
        exam_session = self.create_session()
        self.sign_in()
        # A real database trigger fails the final write; no partial booking survives.
        with self.connect() as conn:
            conn.execute("""CREATE FUNCTION reject_test_booking() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'Test write failure'; END $$""")
            conn.execute("CREATE TRIGGER reject_test_booking BEFORE INSERT ON registrations FOR EACH ROW EXECUTE FUNCTION reject_test_booking()")
        try:
            response = self.book(exam_session)
            self.assertTrue(response.location.endswith("/student/make-appointment"))
            self.assertIn(b"Could not book the appointment", self.client.get(response.location).data)
            self.assertEqual(self.count_booked(exam_session), 0)
        finally:
            with self.connect() as conn:
                conn.execute("DROP TRIGGER reject_test_booking ON registrations")
                conn.execute("DROP FUNCTION reject_test_booking()")
        self.assertTrue(self.book(exam_session).location.endswith("/student/confirmation"))

    def parallel_book(self, pairs):
        barrier = Barrier(len(pairs))

        def attempt(pair):
            student, exam_session = pair
            with self.app.test_client() as client:
                self.sign_in(student, client=client)
                barrier.wait(timeout=10)
                return self.book(exam_session, client).status_code

        with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
            self.assertEqual(list(pool.map(attempt, pairs)), [302] * len(pairs))

    def test_concurrent_last_seat_including_restored_booking(self):
        exam_session = self.create_session(capacity=1)
        with self.connect() as conn:
            second = self.insert_user(conn, "0000000002@student.csn.edu", "student", "0000000002")
            conn.execute("INSERT INTO registrations (session_id,user_id,cancelled) VALUES (%s,%s,TRUE)", (exam_session, second))
        self.parallel_book([(self.student, exam_session), (second, exam_session)])
        self.assertEqual(self.count_booked(exam_session), 1)

    def test_concurrent_bookings_cannot_exceed_student_limit(self):
        self.sign_in()
        for _ in range(2):
            self.book(self.create_session())
        self.parallel_book([(self.student, self.create_session()), (self.student, self.create_session())])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM registrations WHERE NOT cancelled").fetchone()["count"], 3)


if __name__ == "__main__":
    unittest.main()
