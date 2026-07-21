import os
import sqlite3
import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
DATA_DIR = os.environ.get('DATA_DIR', './data')
TOKEN = os.environ.get('REPORT_TOKEN')

os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'records.db')

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS logs (app_name TEXT, timestamp TEXT)')
        conn.execute('DELETE FROM logs WHERE rowid IN (SELECT rowid FROM logs ORDER BY rowid DESC LIMIT -1 OFFSET 100)')

@app.before_request
def auth():
    if request.path == '/ping':
        return None
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f'Bearer {TOKEN}':
        return jsonify({"error": "Unauthorized"}), 401

@app.route('/ping')
def ping():
    return "pong"

@app.route('/report', methods=['POST'])
def report():
    data = request.get_json()
    app_name = data.get('app_name', '未知应用')
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT INTO logs (app_name, timestamp) VALUES (?, ?)', (app_name, now))
        conn.execute('DELETE FROM logs WHERE rowid NOT IN (SELECT rowid FROM logs ORDER BY rowid DESC LIMIT 100)')
    
    return jsonify({"status": "ok"}), 200

@app.route('/activity/summary', methods=['GET'])
def summary():
    with sqlite3.connect(DB_PATH) as conn:
        logs = conn.execute('SELECT app_name, timestamp FROM logs ORDER BY rowid DESC LIMIT 10').fetchall()
    return jsonify({"last_active": logs[0][1] if logs else None, "recent_apps": list(set([l[0] for l in logs]))})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8080)
