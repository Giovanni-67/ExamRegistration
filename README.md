To run this project, open a terminal in VS Code and navigate to the project folder

Create the virtual environment (this only needs to be done once):
python -m venv .venv

Activate the virtual environment (this must be done every time you open a new terminal):
.venv\Scripts\activate

You should see (.venv) at the start of the terminal line.

Install the required Python packages (first time only, or if requirements.txt changes):
python -m pip install -r requirements.txt

Set up private configuration (first time only):

1. Copy `.env.example` to `.env` in the same folder as `app.py`.
2. Fill in `DB_HOST`, `DB_USER`, `DB_PASS`, and `DB_NAME` for your local MySQL database. The supplied `schema.sql` creates a database named `examregdb`.
3. Generate your own login-session signing key in your local terminal:

   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

4. Paste the generated value after `SECRET_KEY=` in your private `.env` file. Do not share it or commit it. Keep the same key between restarts; replacing it logs out existing sessions.

The app requires a private, randomly generated `SECRET_KEY` before it can start. `.env`, its local variants, virtual environments, and Python cache files are ignored by Git. Only `.env.example`, with blank secret fields, belongs in the repository. Never include passwords, generated keys, real student information, or screenshots of private settings in commits or public documentation.

For a future hosted deployment, put these settings in the hosting provider's environment settings. Hosting environment values take priority over `.env`. You can still run the application locally with your separate MySQL settings.

Open MySQL and run the schema.sql file to create the required database tables. This only needs to be done once.
Start the application by running:
python app.py

If it starts successfully, open a browser and click on link provided in terminal.

## Configuration tests

With your virtual environment active, run:

```powershell
python -m unittest discover -s tests -v
```

These tests use temporary configuration and generated test keys. They do not read your private `.env` or require a running MySQL database. They cover signing-key validation, session signing, local configuration, hosting overrides, and Git ignore rules.
