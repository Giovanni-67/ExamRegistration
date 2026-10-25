# Exam Registration

A Flask application for scheduling exam appointments. Students can book, cancel, and review appointments; faculty can create exam sessions. The application uses PostgreSQL, server-rendered HTML templates, and separate CSS files.

## Local setup

Use Python 3.12 and PostgreSQL 16 or newer. DBeaver can manage the PostgreSQL database just as it can manage MySQL.

1. Create and activate a Python virtual environment from the project folder:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   python -m pip install -r requirements.txt
   ```

2. Create a new, empty PostgreSQL database named `examregdb` using DBeaver or PostgreSQL's database tools. Use a local database account with permission to create tables in that database.
3. Copy `.env.example` to `.env` next to `app.py`. Set `DATABASE_URL` to your private PostgreSQL connection URL. The format is documented in the example file; replace placeholders locally. URL-encode special characters in usernames/passwords, or use a provider-generated connection URL.
4. Generate a private login-session signing key on your own computer:

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Paste the generated value after `SECRET_KEY=` in your private `.env`. Keep it stable between restarts; replacing it logs out existing sessions.

5. Create the tables, then start the local development app:

   ```powershell
   flask --app app init-db
   python app.py
   ```

   Open the local URL printed by Flask. Activate the virtual environment each time you open a new terminal.

`init-db` creates missing tables and indexes without deleting existing records. It does not upgrade an older schema or import MySQL data. An empty database has no exams or locations yet; fictional recruiter-demo data will be added in the next development milestone.

## Private configuration

Keep passwords, connection URLs, generated keys, real student information, and screenshots of private settings out of commits and public documentation. Git ignores `.env`, local environment variants, virtual environments, and Python cache files. Only `.env.example`, with blank private fields, belongs in the repository.

The application requires a private `SECRET_KEY` at startup and a `DATABASE_URL` for database operations. Hosted environment settings take priority over `.env`; use the full database provider URL, including its TLS options. The app does not need access to your local MySQL server.

## Moving from the original MySQL setup

This version uses PostgreSQL for both local development and the future hosted demo. Create a separate PostgreSQL database and update the private configuration. Your existing MySQL database is not changed or deleted. `DB_HOST`, `DB_USER`, `DB_PASS`, and `DB_NAME` are no longer used by this version. Copying existing MySQL records is a separate migration task; do not publish a database export containing private information.

## Tests

With the virtual environment active:

```powershell
python -m unittest discover -s tests -v
```

Configuration tests use generated test keys and temporary files; they never load your private `.env`. Database integration tests run when `TEST_DATABASE_URL` is set in your terminal to a disposable PostgreSQL database. Without it, integration tests are explicitly reported as skipped.

The integration suite creates and removes its own uniquely named schema. Its test database account needs permission to create schemas. Tests exercise signup/login, both roles, booking and cancellation, restored appointments, duplicate requests, full sessions, concurrent bookings, transaction rollback, and repeatable initialization. Only fictional test records are used.

GitHub Actions runs the full suite against a temporary PostgreSQL service on pushes and pull requests. It uses only disposable test configuration and does not need production or personal credentials.
