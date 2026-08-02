"""
查岗系统 — HTTP纯接口版（去掉 mcp 依赖，解决 mcp.server.fastmcp 导入失败崩溃）
按日本时间每日刷新：当天使用时长统计，每天零点自动清零
"""

import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "records.db"
JST = timedelta(hours=9)
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "change_me")


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            event TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON records(timestamp)")
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def today_start_utc() -> str:
    """返回日本时间今天零点对应的 UTC ISO 字符串"""
    now_jst = datetime.utcnow() + JST
    today_jst_midnight = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    return (today_jst_midnight - JST).isoformat()


def build_sessions(rows):
    """只统计日本时间今天内的使用时长（每日刷新）"""
    start = today_start_utc()
    sessions = {}
    opens = {}
    for r in rows:
        app, ev, ts_str = r["app_name"], r["event"], r["timestamp"]
        if ts_str < start:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if ev == "open":
            opens[app] = ts
        elif ev == "close" and app in opens:
            sessions[app] = sessions.get(app, 0) + (ts - opens[app]).total_seconds()
            del opens[app]
    return sessions


app = FastAPI(title="查岗系统")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class ReportBody(BaseModel):
    app_name: str
    event: str


@app.get("/ping")
async def ping():
    return "pong"


@app.post("/report")
async def report(body: ReportBody, req: Request):
    auth = req.headers.get("Authorization", "")
    if auth != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(401, "Unauthorized")
    if body.event not in ("open", "close"):
        raise HTTPException(400, "event must be open or close")
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO records (app_name, event, timestamp) VALUES (?, ?, ?)",
        (body.app_name, body.event, now),
    )
    conn.execute("DELETE FROM records WHERE id NOT IN (SELECT id FROM records ORDER BY id DESC LIMIT 500)")
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/activity/summary")
async def summary():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT app_name, event, timestamp FROM records ORDER BY id DESC LIMIT 5")
    recent = cur.fetchall()
    cur.execute("SELECT app_name, event, timestamp FROM records ORDER BY id ASC")
    all_rows = cur.fetchall()
    conn.close()
    sessions = build_sessions(all_rows)
    last = recent[0]["timestamp"] if recent else None
    return {
        "last_active": last,
        "recent_apps": [r["app_name"] for r in recent],
        "today_start": today_start_utc(),
        "sessions": {k: int(v) for k, v in sessions.items()},
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
