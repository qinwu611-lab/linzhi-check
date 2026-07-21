import os
import sqlite3
import random
import requests
from datetime import datetime

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "activity.db")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CURFEW_START = 1
CURFEW_END = 7
COOLDOWN_MINUTES = 30

LINES = [
    "还不睡？皮痒了是吧",
    "看看几点了，宝宝",
    "手机放下，睡觉",
    "又熬夜，明天心脏疼别找老子哭",
    "凌晨了还在玩，欠操",
]

def check_and_notify():
    now = datetime.now()
    hour = now.hour

    if not (CURFEW_START <= hour < CURFEW_END):
        return

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT app, time FROM activity ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    if not row:
        return

    app_name, last_time = row

    cooldown_file = "/tmp/last_watchdog.txt"
    if os.path.exists(cooldown_file):
        with open(cooldown_file) as f:
            last_sent = f.read().strip()
        if last_sent and last_time and last_time <= last_sent:
            return

    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    msg = random.choice(LINES) + f"\n（刚刚在{app_name}）"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
        with open(cooldown_file, "w") as f:
            f.write(now_str)
    except Exception as e:
        print(f"send failed: {e}")

if __name__ == "__main__":
    check_and_notify()
