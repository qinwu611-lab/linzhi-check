import os
import sqlite3
import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# 核心改动：直接使用当前目录，不管Railway存不存 /data
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'records.db')
TOKEN = os.environ.get('REPORT_TOKEN', 'change_me')

def init_db():
    """初始化数据库表（如果不存在则自动创建）"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

def clean_old_records():
    """清理旧记录，只保留最新的100条"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 100)')
    conn.commit()
    conn.close()

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
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT INTO logs (app_name, timestamp) VALUES (?, ?)', (app_name, now))
    conn.commit()
    conn.close()
    
    clean_old_records()
    return jsonify({"status": "ok"}), 200

@app.route('/activity/summary', methods=['GET'])
def summary():
    conn = sqlite3.connect(DB_PATH)
    logs = conn.execute('SELECT app_name, timestamp FROM logs ORDER BY id DESC LIMIT 10').fetchall()
    conn.close()
    
    last_active = logs[0][1] if logs else None
    recent_apps = list(set([l[0] for l in logs]))
    
    return jsonify({"last_active": last_active, "recent_apps": recent_apps})

init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
