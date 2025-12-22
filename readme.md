Setup: py -m venv .venv && .venv\Scripts\Activate
py -m pip install -r requirements.txt
Run schema.sql in MySQL
Copy .env.example -> .env (fill in DB creds)
py app.py -> http://127.0.0.1:5000

For my system: 
cd 'C:\Users\herog\Downloads\VSCODE\exam\examreg'
venv\Scripts\activate
python app.py