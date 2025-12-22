To run this project, open a terminal in VS Code and navigate to the project folder

Create the virtual environment (this only needs to be done once):
python -m venv .venv

Activate the virtual environment (this must be done every time you open a new terminal):
.venv\Scripts\activate

You should see (.venv) at the start of the terminal line.

Install the required Python packages (first time only, or if requirements.txt changes):
python -m pip install -r requirements.txt

Set up environment variables by copying the file named .env.example, renaming the copy to .env, and filling in your MySQL database credentials inside the .env file. Do not upload the .env file to GitHub.

Open MySQL and run the schema.sql file to create the required database tables. This only needs to be done once.
Start the application by running:
python app.py

If it starts successfully, open a browser and click on link provided in terminal.