"""Production entry point. Local development can continue using python app.py."""

import os

import psycopg
from waitress import serve


def main():
    try:
        port = int(os.getenv("PORT", "10000"))
        if not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise SystemExit("PORT must be a number from 1 to 65535.") from None

    from app import app, initialize_database

    if app.config["APP_ENV"] != "production":
        raise SystemExit("Set APP_ENV=production before using the hosted server.")

    # Free Render services have no separate pre-deploy step. Initialization is
    # repeatable, so cold starts and redeploys keep existing fictional data.
    try:
        initialize_database()
    except (psycopg.Error, RuntimeError):
        raise SystemExit(
            "Database startup failed. Check the private DATABASE_URL, TLS settings, "
            "and schema permissions in the hosting dashboard."
        ) from None

    app.debug = False
    serve(app, host="0.0.0.0", port=port, threads=4,
          max_request_body_size=64 * 1024, expose_tracebacks=False)


if __name__ == "__main__":
    main()
