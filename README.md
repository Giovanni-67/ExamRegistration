# Exam Registration

A Flask application for scheduling exam appointments. Students can book, cancel, and review appointments; faculty can create exam sessions. The application uses PostgreSQL, server-rendered HTML templates, and separate CSS files.

**Live demo status:** not deployed yet. The demo and deployment configuration are implemented; a public link will be added only after the hosted workflows are verified.

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

`init-db` creates missing tables and indexes without deleting existing records. It does not upgrade an older schema or import MySQL data. Regular account tables start empty; demos create their own fictional sample records.

## Recruiter demos

After configuring PostgreSQL and running `flask --app app init-db`, set `DEMO_ENABLED=true` in your private `.env` and restart the app. The home page offers **Try Student Demo** and **Try Faculty Demo**, with no signup or shared password needed.

- Each visitor gets separate PostgreSQL tables in a temporary schema. Demo queries cannot fall back to regular application tables.
- Both role views share that visitor's workspace. Book or cancel as a student, switch to faculty to create an exam session, then switch back to see it.
- All records are fictional. Sample dates are relative to the day the demo starts; history includes a past appointment and a cancelled booking.
- The banner includes role switching, **Reset my demo**, and **Exit demo**. Reset replaces only that visitor's records. Exit removes that workspace immediately.
- A workspace expires two hours after creation. New demo starts remove expired workspaces, and the `flask --app app cleanup-demos` command can also remove them. Cleanup runs on demand, not on a paid scheduler.
- At most 20 workspaces can exist at once, and each demo is limited to 50 exam sessions. Visitors see a message if the demo is full. Expired data may remain stored until the next cleanup, but expired sessions cannot access it.

Use `DEMO_ONLY=true` together with `DEMO_ENABLED=true` for a public portfolio deployment. This hides account signup/login and prevents visitors from submitting personal signup information. Leave both false for the regular local account workflow. The PostgreSQL account needs permission to create and drop schemas in the configured database; demos do not need a separate database service or a paid plan.

## Free hosting setup

The included `render.yaml` defines one **Render Free web service**, using a separate **Neon Free PostgreSQL project**. It does not create a paid service, persistent disk, scheduled job, or Render trial database. Account creation and deployment are still required.

1. Sign in to Neon and create a separate, empty **Free** project for fictional demo data. Do not upload a local database export or real account records.
2. In Neon's connection dialog, use the direct PostgreSQL connection URL and keep its TLS parameters (`sslmode=require` or stronger). Treat the entire URL as a password.
3. Sign in to Render, choose **New > Blueprint**, and connect this repository's `main` branch. Review the proposed resources: there should be one Free web service and no Render database.
4. Enter the Neon URL only in Render's private `DATABASE_URL` prompt. The Blueprint generates a new `SECRET_KEY` and sets `APP_ENV=production`, `DEMO_ENABLED=true`, and `DEMO_ONLY=true`. Never copy private settings into GitHub, screenshots, or chat.
5. Deploy. Render installs the pinned dependencies and runs `python serve.py`. This initializes missing tables transactionally, then starts Waitress on the provider's `PORT`. Startup stops with a safe message if the database cannot be initialized. Existing records are not deleted by initialization.
6. Open the actual HTTPS address shown by Render. Verify student booking/cancellation/history, faculty session creation, role switching, reset/exit, and isolation in a second browser session before sharing the link.

Production startup requires encrypted PostgreSQL connections, disables Flask debugging, and uses HTTPS-only, HttpOnly, SameSite=Lax session cookies. It limits form bodies to 64 KiB. `/health` checks that the web process responds without querying the database; it is not a database availability check and does not keep Neon awake.

These are ongoing free plans, not a guarantee of free hosting forever. Render sleeps idle Free services, so the first visit can be slow. Neon has free storage/compute limits. Review the current [Render Free limitations](https://render.com/docs/free) and [Neon Free plan](https://neon.com/pricing); remain on Free plans and do not enable paid resources or billing upgrades. The local app does not need to stay running for the hosted demo.

## Private configuration

Keep passwords, connection URLs, generated keys, real student information, and screenshots of private settings out of commits and public documentation. Git ignores `.env`, local environment variants, virtual environments, and Python cache files. Only `.env.example`, with blank private fields, belongs in the repository.

The application requires a private `SECRET_KEY` at startup and a `DATABASE_URL` for database operations. Hosted environment settings take priority over `.env`; use the full database provider URL, including its TLS options. Keep `APP_ENV=development` for ordinary local HTTP development. The app does not need access to your local MySQL server.

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
