"""
查岗系统 — HTTP纯接口版（去掉 mcp 依赖，解决 mcp.server.fastmcp 导入失败崩溃）
按日本时间每日刷新：当天使用时长统计，每天零点自动清零
加：iPhone 快捷指令上报电量/位置/天气/亮度/音量/自定义消息/步数，存 life_states，查岗汇总时一并返回
"""

import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battery INTEGER,
            location TEXT,
            weather TEXT,
            brightness REAL,
            volume REAL,
            steps INTEGER,
            note TEXT,
            device TEXT DEFAULT 'iphone',
            timestamp TEXT NOT NULL
        )
    """)
    # 兼容旧库：给已有的 life_states 补 steps 列
    try:
        conn.execute("ALTER TABLE life_states ADD COLUMN steps INTEGER")
    except sqlite3.OperationalError:
        pass  # 列已存在
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
    """前台切换模型：按时间排序，谁在打开就记谁的时长，各App不重叠，总量=当天活跃总时长"""
    start = today_start_utc()
    events = []
    for r in rows:
        app, ev, ts_str = r["app_name"], r["event"], r["timestamp"]
        if not app:
            continue
        if ts_str < start:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        events.append((ts, app, ev))
    events.sort(key=lambda x: x[0])
    sessions = {}
    current = None
    current_start = None
    now = datetime.utcnow()
    for ts, app, ev in events:
        if ev != "open":
            continue
        if current and current_start is not None:
            sessions[current] = sessions.get(current, 0) + (ts - current_start).total_seconds()
        current = app
        current_start = ts
    if current and current_start is not None:
        last_close = now
        for t, a, e in events:
            if e == "close" and a == current and t > current_start:
                last_close = t
        if last_close < current_start:
            last_close = now
        sessions[current] = sessions.get(current, 0) + max(0, (last_close - current_start).total_seconds())
    return {k: int(v) for k, v in sessions.items() if v > 0}


def coerce_num(v):
    """把 int/float/字符串 统一转成 float；转不了就返回 None"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def coerce_int(v):
    """把 int/字符串 统一转成 int；转不了就返回 None"""
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


app = FastAPI(title="查岗系统")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class ReportBody(BaseModel):
    app_name: str
    event: str


class LifeBody(BaseModel):
    battery: int | str | None = None
    location: str | None = None
    weather: str | None = None
    brightness: int | float | str | None = None
    volume: int | float | str | None = None
    steps: int | str | None = None
    note: str | None = None
    device: str = "iphone"

    @field_validator("brightness", "volume")
    @classmethod
    def ensure_float(cls, v):
        return coerce_num(v)

    @field_validator("steps")
    @classmethod
    def ensure_int(cls, v):
        return coerce_int(v)


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


@app.post("/life")
async def report_life(body: LifeBody, req: Request):
    auth = req.headers.get("Authorization", "")
    if auth != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(401, "Unauthorized")
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO life_states (battery, location, weather, brightness, volume, steps, note, device, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (body.battery, body.location, body.weather, body.brightness, body.volume, body.steps, body.note, body.device, now),
    )
    conn.execute("DELETE FROM life_states WHERE id NOT IN (SELECT id FROM life_states ORDER BY id DESC LIMIT 200)")
    conn.commit()
    conn.close()
    return {"status": "ok", "received": now}


@app.get("/activity/summary")
async def summary():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT app_name, event, timestamp FROM records ORDER BY id DESC LIMIT 5")
    recent = cur.fetchall()
    cur.execute("SELECT app_name, event, timestamp FROM records ORDER BY id ASC")
    all_rows = cur.fetchall()
    life = conn.execute(
        "SELECT battery, location, weather, brightness, volume, steps, note, device, timestamp FROM life_states ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    sessions = build_sessions(all_rows)
    last = recent[0]["timestamp"] if recent else None
    return {
        "last_active": last,
        "recent_apps": [r["app_name"] for r in recent],
        "today_start": today_start_utc(),
        "sessions": {k: int(v) for k, v in sessions.items()},
        "life": {
            "battery": life["battery"] if life else None,
            "location": life["location"] if life else None,
            "weather": life["weather"] if life else None,
            "brightness": life["brightness"] if life else None,
            "volume": life["volume"] if life else None,
            "steps": life["steps"] if life else None,
            "note": life["note"] if life else None,
            "device": life["device"] if life else None,
            "timestamp": life["timestamp"] if life else None,
        } if life else None,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
