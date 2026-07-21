import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
from functools import wraps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "records.db")

app = Flask(__name__)
TOKEN = "change_me"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            event TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    c.execute("DELETE FROM records WHERE id NOT IN (SELECT id FROM records ORDER BY id DESC LIMIT 500)")
    conn.commit()
    conn.close()

init_db()

def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {TOKEN}":
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/ping")
def ping():
    return "pong"

@app.route("/report", methods=["POST"])
@require_token
def report():
    data = request.get_json(force=True)
    app_name = data.get("app_name", "").strip()
    event = data.get("event", "open").strip()
    if not app_name:
        return jsonify({"error": "app_name required"}), 400
    if event not in ("open", "close"):
        return jsonify({"error": "event must be open or close"}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO records (app_name, event, timestamp) VALUES (?, ?, ?)",
        (app_name, event, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/activity/summary")
@require_token
def summary():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT app_name, event, timestamp FROM records ORDER BY id DESC LIMIT 200")
    rows = c.fetchall()
    conn.close()

    sessions = {}
    for app_name, event, ts in reversed(rows):
        if app_name not in sessions:
            sessions[app_name] = {"open_time": None, "close_time": None, "durations": []}
        if event == "open" and sessions[app_name]["open_time"] is None:
            sessions[app_name]["open_time"] = ts
        elif event == "close" and sessions[app_name]["open_time"] is not None:
            open_ts = sessions[app_name]["open_time"]
            fmt = "%Y-%m-%d %H:%M:%S"
            diff = (datetime.strptime(ts, fmt) - datetime.strptime(open_ts, fmt)).total_seconds()
            sessions[app_name]["durations"].append(round(diff))
            sessions[app_name]["open_time"] = None

    recent_apps = []
    for app_name, event, ts in rows[:50]:
        if app_name not in [r["name"] for r in recent_apps]:
            recent_apps.append({"name": app_name, "event": event, "time": ts})

    result = {
        "last_active": rows[0][2] if rows else None,
        "recent_apps": [r["name"] for r in recent_apps],
        "sessions": {}
    }
    for app_name, data in sessions.items():
        if data["durations"]:
            result["sessions"][app_name] = data["durations"][-1]
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
