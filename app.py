from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, abort
)
from flask_bcrypt import Bcrypt
import click
import psycopg
from psycopg.rows import dict_row
import os, re, calendar as pycal
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from functools import wraps
# add/confirm these imports
from datetime import datetime, date, time, timedelta
import calendar as cal
from flask import render_template, request, session, redirect, url_for, flash

# -----------------------
# Load .env next to this file
# -----------------------
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

# -----------------------
# Flask / Bcrypt setup
# -----------------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
# This key signs login sessions; a public or missing key cannot protect them.
if not app.secret_key or not app.secret_key.strip() or app.secret_key.strip() == "dev-secret":
    raise RuntimeError(
        "Set SECRET_KEY to a private, randomly generated value in your .env "
        "file or hosting environment before starting the app."
    )
bcrypt = Bcrypt(app)
app.config["DATABASE_URL"] = os.getenv("DATABASE_URL", "")

# -----------------------
# DB connection helper
# -----------------------
def get_conn():
    database_url = app.config["DATABASE_URL"]
    if not database_url.strip():
        raise RuntimeError("Set DATABASE_URL in your private .env or hosting environment.")
    # Named columns keep the templates readable; provider TLS options stay in the URL.
    return psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10)


@app.cli.command("init-db")
def init_db():
    """Create missing PostgreSQL tables without deleting existing records."""
    with get_conn() as conn:
        conn.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
    click.echo("Database tables are ready.")

# -----------------------
# Email rules
# -----------------------
STUDENT_RE = re.compile(r"^(\d{10})@student\.csn\.edu$", re.IGNORECASE)
FACULTY_RE = re.compile(r"^[A-Za-z]+\.[A-Za-z]+@csn\.edu$", re.IGNORECASE)

def detect_role(email: str):
    if not email:
        return None
    if STUDENT_RE.match(email):
        return "student"
    if FACULTY_RE.match(email):
        return "faculty"
    return None

# -----------------------
# Auth decorators
# -----------------------
def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get("user_id"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return fn(*a, **k)
    return w

def student_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if session.get("role") != "student":
            abort(403)
        return fn(*a, **k)
    return w

def faculty_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if session.get("role") != "faculty":
            abort(403)
        return fn(*a, **k)
    return w

# -----------------------
# Calendar helpers
# -----------------------
def month_bounds(year: int, month: int):
    first = datetime(year, month, 1)
    _, last_day = pycal.monthrange(year, month)
    last = datetime(year, month, last_day, 23, 59, 59)
    return first, last

def fetch_sessions_between(start_dt: datetime, end_dt: datetime, user_id: int | None = None):
    """
    Pull sessions between two datetimes, with aggregates.
    If user_id is provided, also flag whether this user is already registered.
    """
    conn = get_conn()
    cur = conn.cursor()

    base_select = """
        SELECT
            es.id,
            e.exam_code,
            es.session_datetime,
            l.campus_name, l.building_name, l.room_number,
            es.capacity,
            COUNT(r.id) AS booked
        FROM examsessions es
        JOIN exams e      ON e.id = es.exam_id
        JOIN locations l  ON l.id = es.location_id
        LEFT JOIN registrations r ON r.session_id = es.id AND r.cancelled = FALSE
        WHERE es.session_datetime BETWEEN %s AND %s
    """

    group_order = " GROUP BY es.id, e.id, l.id ORDER BY es.session_datetime ASC"

    if user_id:
        # We won't return already_registered here because the student dashboard no longer shows buttons.
        # But we might still want it in the "upcoming" sidebar; compute separately when needed.
        cur.execute(base_select + group_order, (start_dt, end_dt))
    else:
        cur.execute(base_select + group_order, (start_dt, end_dt))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def fetch_upcoming_for_student(user_id: int, limit: int = 10):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            es.id,
            e.exam_code,
            es.session_datetime,
            l.campus_name, l.building_name, l.room_number,
            es.capacity,
            (
              SELECT COUNT(*) FROM registrations r2
              WHERE r2.session_id = es.id AND r2.cancelled = FALSE
            ) AS booked
        FROM registrations r
        JOIN examsessions es ON es.id = r.session_id
        JOIN exams e          ON e.id = es.exam_id
        JOIN locations l      ON l.id = es.location_id
        WHERE r.user_id = %s
          AND r.cancelled = FALSE
          AND es.session_datetime >= NOW()
        ORDER BY es.session_datetime ASC
        LIMIT %s
        """,
        (user_id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

# -----------------------
# Routes
# -----------------------
@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("student_dashboard" if session.get("role") == "student" else "faculty_dashboard"))
    return render_template("home.html", user_name=session.get("user_name"))

# --- SIGN UP ---
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email     = request.form.get("email", "").strip().lower()
        password  = request.form.get("password", "")
        confirm   = request.form.get("confirm", "")
        role_sel  = request.form.get("role", "student").strip().lower()

        if not full_name or not email or not password or not confirm:
            flash("All fields are required.", "error")
            return redirect(url_for("signup"))

        detected = detect_role(email)
        if detected is None:
            flash("Use CSN email: student=10digits@student.csn.edu, faculty=firstname.lastname@csn.edu", "error")
            return redirect(url_for("signup"))

        if detected != role_sel:
            flash("Selected role does not match email pattern.", "error")
            return redirect(url_for("signup"))

        # Faculty: min 7 characters
        if detected == "faculty" and len(password) < 7:
            flash("Faculty password must be at least 7 characters.", "error")
            return redirect(url_for("signup"))

        # Students: allow any password (you can enforce rules if you want)
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("signup"))

        pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")

        # Faculty have no student ID. NULL allows multiple faculty accounts.
        nshe = STUDENT_RE.match(email).group(1) if detected == "student" else None

        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (email, nshe, full_name, password_hash, role) VALUES (%s,%s,%s,%s,%s)",
                (email, nshe, full_name, pw_hash, detected),
            )
            conn.commit()
            cur.close(); conn.close()
            flash("Account created! Please log in.", "success")
            return redirect(url_for("login"))
        except psycopg.IntegrityError:
            try: cur.close(); conn.close()
            except: pass
            flash("That email is already registered.", "error")
            return redirect(url_for("signup"))

    return render_template("signup.html")

# --- LOGIN ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email    = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name, password_hash, role FROM users WHERE email=%s", (email,))
    user = cur.fetchone()
    cur.close(); conn.close()

    if not user or not bcrypt.check_password_hash(user["password_hash"], password):
        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    session["user_id"]   = user["id"]
    session["user_name"] = user["full_name"]
    session["role"]      = user.get("role", "student")

    flash("Logged in!", "success")
    return redirect(url_for("student_dashboard" if session["role"] == "student" else "faculty_dashboard"))

# --- LOGOUT ---
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("home"))

# -----------------------
# STUDENT: Dashboard (Calendar)
# -----------------------
@app.route("/student")
@login_required
@student_required
def student_dashboard():
    # --- figure out which month to show ---
    try:
        year  = int(request.args.get("year", 0)) or date.today().year
        month = int(request.args.get("month", 0)) or date.today().month
    except ValueError:
        year  = date.today().year
        month = date.today().month

    # month range
    _, last_day = cal.monthrange(year, month)
    month_start = datetime(year, month, 1, 0, 0, 0)
    month_end   = datetime(year, month, last_day, 23, 59, 59)

    # “today at midnight” to hide past sessions
    today_start = datetime.combine(date.today(), time.min)

    # prev/next month helpers
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)

    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_conn()
    cur  = conn.cursor()

    # Pull ONLY sessions the student has registered for (and not cancelled),
    # and hide anything before today. Still constrain to the viewed month.
    cur.execute(
        """
        SELECT
            s.id,
            s.session_datetime,
            s.capacity,
            s.duration_minutes,
            e.exam_code,
            l.campus_name,
            l.building_name,
            l.room_number,
            COALESCE(b.booked, 0) AS booked,
            r.id AS registration_id
        FROM registrations r
        JOIN examsessions s ON s.id = r.session_id
        JOIN exams e        ON e.id = s.exam_id
        JOIN locations l    ON l.id = s.location_id
        LEFT JOIN (
            SELECT session_id, COUNT(*) AS booked
            FROM registrations
            WHERE cancelled = FALSE
            GROUP BY session_id
        ) b ON b.session_id = s.id
        WHERE r.user_id = %s
          AND r.cancelled = FALSE
          AND s.session_datetime >= %s
          AND s.session_datetime >= %s
          AND s.session_datetime <= %s
        ORDER BY s.session_datetime
        """,
        (user_id, today_start, month_start, month_end)
    )
    sessions = cur.fetchall()

    # Also build a short "upcoming" list (next 10 your active regs from today forward)
    cur.execute(
        """
        SELECT
            s.id,
            s.session_datetime,
            s.capacity,
            s.duration_minutes,
            e.exam_code,
            l.campus_name,
            l.building_name,
            l.room_number,
            COALESCE(b.booked, 0) AS booked,
            r.id AS registration_id
        FROM registrations r
        JOIN examsessions s ON s.id = r.session_id
        JOIN exams e        ON e.id = s.exam_id
        JOIN locations l    ON l.id = s.location_id
        LEFT JOIN (
            SELECT session_id, COUNT(*) AS booked
            FROM registrations
            WHERE cancelled = FALSE
            GROUP BY session_id
        ) b ON b.session_id = s.id
        WHERE r.user_id = %s
          AND r.cancelled = FALSE
          AND s.session_datetime >= %s
        ORDER BY s.session_datetime
        LIMIT 10
        """,
        (user_id, today_start)
    )
    upcoming = cur.fetchall()

    cur.close()
    conn.close()

    # Group sessions by YYYY-MM-DD for the calendar cells
    by_day = {}
    for s in sessions:
        # Ensure session_datetime is a datetime
        dt = s["session_datetime"]
        day_key = dt.strftime("%Y-%m-%d")
        by_day.setdefault(day_key, []).append(s)

    return render_template(
        "student_dashboard.html",
        cal=cal,
        year=year,
        month=month,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        by_day=by_day,
        upcoming=upcoming
    )

# -----------------------
# STUDENT: Make Appointment (list sessions not already enrolled)
# -----------------------
@app.route("/student/make-appointment", methods=["GET", "POST"])
@login_required
@student_required
def student_make_appointment():
    """List future sessions and book or restore an appointment in one transaction."""
    user_id = session["user_id"]
    if request.method == "GET":
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT es.id, e.exam_code, e.description,
                       es.session_datetime, es.duration_minutes,
                       l.campus_name, l.building_name, l.room_number,
                       (SELECT COUNT(*) FROM registrations r
                        WHERE r.session_id = es.id AND NOT r.cancelled) AS booked,
                       es.capacity
                FROM examsessions es
                JOIN exams e ON e.id = es.exam_id
                JOIN locations l ON l.id = es.location_id
                WHERE es.session_datetime >= LOCALTIMESTAMP
                  AND NOT EXISTS (
                      SELECT 1 FROM registrations r
                      WHERE r.session_id = es.id AND r.user_id = %s AND NOT r.cancelled
                  )
                ORDER BY es.session_datetime ASC
                """,
                (user_id,),
            )
            sessions = cur.fetchall()
        for exam_session in sessions:
            exam_session["is_full"] = exam_session["booked"] >= exam_session["capacity"]
        return render_template("student_make_appointment.html", sessions=sessions)

    session_id = request.form.get("session_id", "").strip()
    if not session_id.isascii() or not session_id.isdigit() or len(session_id) > 10:
        flash("Please choose a valid session.", "error")
        return redirect(url_for("student_make_appointment"))
    session_id = int(session_id)
    if not 0 < session_id <= 2147483647:
        flash("Please choose a valid session.", "error")
        return redirect(url_for("student_make_appointment"))

    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Serialize bookings by this student so simultaneous clicks cannot exceed 3.
            cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
            if not cur.fetchone():
                session.clear()
                return redirect(url_for("login"))

            # Both new and restored bookings lock the session before counting seats.
            cur.execute(
                "SELECT id, capacity, session_datetime FROM examsessions WHERE id = %s FOR UPDATE",
                (session_id,),
            )
            exam_session = cur.fetchone()
            if not exam_session:
                flash("That exam session no longer exists.", "error")
                return redirect(url_for("student_make_appointment"))
            cur.execute("SELECT LOCALTIMESTAMP AS now")
            if exam_session["session_datetime"] < cur.fetchone()["now"]:
                flash("That exam session has already started.", "error")
                return redirect(url_for("student_make_appointment"))

            cur.execute(
                "SELECT id, cancelled FROM registrations WHERE user_id = %s AND session_id = %s",
                (user_id, session_id),
            )
            existing = cur.fetchone()
            if existing and not existing["cancelled"]:
                flash("You are already registered for that session.", "info")
                return redirect(url_for("student_dashboard"))

            cur.execute(
                """
                SELECT COUNT(*) AS active_count
                FROM registrations r JOIN examsessions es ON es.id = r.session_id
                WHERE r.user_id = %s AND NOT r.cancelled AND es.session_datetime >= LOCALTIMESTAMP
                """,
                (user_id,),
            )
            if cur.fetchone()["active_count"] >= 3:
                flash("You already have 3 active exam appointments. Cancel one before booking another.", "error")
                return redirect(url_for("student_dashboard"))

            # A separate query sees bookings committed while we waited for the lock.
            cur.execute(
                "SELECT COUNT(*) AS booked FROM registrations WHERE session_id = %s AND NOT cancelled",
                (session_id,),
            )
            if cur.fetchone()["booked"] >= exam_session["capacity"]:
                flash("Sorry, that session just filled up.", "error")
                return redirect(url_for("student_make_appointment"))

            cur.execute(
                """
                INSERT INTO registrations (session_id, user_id) VALUES (%s, %s)
                ON CONFLICT (user_id, session_id) DO UPDATE
                SET cancelled = FALSE, cancelled_at = NULL, registered_at = LOCALTIMESTAMP
                """,
                (session_id, user_id),
            )
    except psycopg.Error:
        # The connection block rolls back before returning to the form.
        flash("Could not book the appointment. Please try again.", "error")
        return redirect(url_for("student_make_appointment"))
    # The connection block commits before we show a successful confirmation.
    return redirect(url_for("student_confirmation"))

# Confirmation page after successful registration
@app.route("/student/confirmation")
@login_required
@student_required
def student_confirmation():
    return render_template("student_confirmation.html")

# -----------------------
# STUDENT: Cancel Appointments (page + action)
# -----------------------
@app.route("/student/cancel-appointments", methods=["GET"])
@login_required
@student_required
def student_cancel_page():
    user_id = session["user_id"]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.id AS registration_id,
            es.id AS session_id,
            e.exam_code,
            es.session_datetime,
            l.campus_name, l.building_name, l.room_number
        FROM registrations r
        JOIN examsessions es ON es.id = r.session_id
        JOIN exams e          ON e.id = es.exam_id
        JOIN locations l      ON l.id = es.location_id
        WHERE r.user_id = %s
          AND r.cancelled = FALSE
          AND es.session_datetime >= NOW()
        ORDER BY es.session_datetime ASC
        """,
        (user_id,),
    )
    active_regs = cur.fetchall()
    cur.close(); conn.close()
    return render_template("student_cancel_appointments.html", active_regs=active_regs)

@app.route("/student/cancel/<int:registration_id>", methods=["POST"])
@login_required
@student_required
def student_cancel(registration_id: int):
    user_id = session["user_id"]
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE registrations
            SET cancelled = TRUE, cancelled_at = NOW()
            WHERE id = %s AND user_id = %s AND cancelled = FALSE
            """,
            (registration_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            flash("Nothing to cancel (already canceled or not found).", "info")
        else:
            flash("Appointment canceled.", "success")
    except psycopg.Error:
        conn.rollback()
        flash("Could not cancel the appointment. Please try again.", "error")
    finally:
        cur.close(); conn.close()

    return redirect(url_for("student_cancel_page"))

# -----------------------
# STUDENT: Appointment History
# -----------------------
@app.route("/student/history")
@login_required
@student_required
def student_history():
    user_id = session["user_id"]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.id AS registration_id,
            es.session_datetime,
            e.exam_code,
            r.cancelled,
            r.cancelled_at,
            r.registered_at,
            l.campus_name,
            l.building_name,
            l.room_number
        FROM registrations r
        JOIN examsessions es ON es.id = r.session_id
        JOIN exams e          ON e.id = es.exam_id
        JOIN locations l      ON l.id = es.location_id
        WHERE r.user_id = %s
        ORDER BY es.session_datetime DESC, r.id DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()

    now = datetime.now()
    for row in rows:
        if row["cancelled"]:
            if row["cancelled_at"]:
                row["status"] = f"Canceled ({row['cancelled_at'].strftime('%b %d, %Y')})"
            else:
                row["status"] = "Canceled"
        else:
            # upcoming vs attended
            if row["session_datetime"] >= now:
                row["status"] = "Upcoming"
            else:
                row["status"] = "Attended"

    # IMPORTANT: pass as 'rows' because your template uses 'rows'
    return render_template("student_history.html", rows=rows)

# -----------------------
# FACULTY: Dashboard + Create Session
# -----------------------
@app.route("/faculty", defaults={"year": None, "month": None})
@app.route("/faculty/<int:year>/<int:month>")
@login_required
@faculty_required
def faculty_dashboard(year, month):
    now = datetime.now()
    year = year or now.year
    month = month or now.month

    start_dt, end_dt = month_bounds(year, month)
    sessions = fetch_sessions_between(start_dt, end_dt)

    by_day = {}
    for s in sessions:
        iso = s["session_datetime"].strftime("%Y-%m-%d")
        by_day.setdefault(iso, []).append(s)

    prev_month_dt = (datetime(year, month, 15) - timedelta(days=31))
    next_month_dt = (datetime(year, month, 15) + timedelta(days=31))

    return render_template(
        "faculty_dashboard.html",
        year=year,
        month=month,
        cal=pycal,
        by_day=by_day,
        prev_year=prev_month_dt.year,
        prev_month=prev_month_dt.month,
        next_year=next_month_dt.year,
        next_month=next_month_dt.month,
    )

@app.route("/faculty/sessions/new", methods=["GET", "POST"])
@login_required
@faculty_required
def faculty_new_session():
    if request.method == "POST":
        exam_id   = int(request.form.get("exam_id", "0"))
        location_id = int(request.form.get("location_id", "0"))
        date_str  = request.form.get("date")   # YYYY-MM-DD
        time_str  = request.form.get("time")   # HH:MM
        capacity  = int(request.form.get("capacity", "20"))

        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except Exception:
            flash("Invalid date or time.", "error")
            return redirect(url_for("faculty_new_session"))

        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO examsessions (exam_id, session_datetime, location_id, creator_id, proctor_id, capacity)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (exam_id, dt, location_id, session.get("user_id"), session.get("user_id"), capacity),
            )
            conn.commit()
            flash("Exam session created.", "success")
            return redirect(url_for("faculty_dashboard"))
        except psycopg.Error:
            conn.rollback()
            flash("Could not create the session. Check the details and try again.", "error")
        finally:
            cur.close(); conn.close()

    # GET: load exams & locations for form
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, exam_code FROM exams ORDER BY exam_code ASC")
    exams = cur.fetchall()
    cur.execute(
        "SELECT id, campus_name, building_name, room_number FROM locations ORDER BY campus_name, building_name, room_number"
    )
    locations = cur.fetchall()
    cur.close(); conn.close()

    return render_template("faculty_new_session.html", exams=exams, locations=locations)

# -----------------------
# Minimal error handlers
# -----------------------
@app.errorhandler(403)
def _403(_):
    return "Forbidden", 403

@app.errorhandler(404)
def _404(_):
    return "Not Found", 404

# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    app.run(debug=True)
