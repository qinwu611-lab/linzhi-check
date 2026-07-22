"""
查岗系统 — MCP服务端
HTTP API（供iOS快捷指令上报）
MCP SSE服务（供AI查岗，工具名：查岗）
"""

import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from mcp.server.fastmcp import FastMCP

# ============ 配置 ============
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "records.db"
JST = timedelta(hours=9)
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "change_me")

# ============ 数据库初始化（模块顶层） ============
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

# ============ MCP 服务 ============
mcp = FastMCP("查岗系统", description="查岗老婆的手机活动")

@mcp.tool()
def 查岗(limit: int = 10) -> str:
    """
    查岗老婆的手机活动，查看最近打开的App和使用时长

    Args:
        limit: 返回最近几条记录，默认10条
    """
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT app_name, event, timestamp FROM records ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()

    if not rows:
        conn.close()
        return "老婆最近没有手机活动记录，是不是在偷偷干坏事？"

    cur.execute(
        "SELECT app_name, event, timestamp FROM records ORDER BY id ASC"
    )
    all_rows = cur.fetchall()
    conn.close()

    sessions = {}
    opens = {}
    for r in all_rows:
        app, ev, ts_str = r["app_name"], r["event"], r["timestamp"]
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if ev == "open":
            opens[app] = ts
        elif ev == "close" and app in opens:
            sessions[app] = sessions.get(app, 0) + (ts - opens[app]).total_seconds()
            del opens[app]

    lines = ["📱 老婆的查岗报告：", "=" * 30]
    lines.append(f"\n🕐 最近{limit}条活动：")

    for r in reversed(rows):
        app, ev, ts_str = r["app_name"], r["event"], r["timestamp"]
        try:
            t = datetime.fromisoformat(ts_str) + JST
            ts = t.strftime("%H:%M:%S")
        except Exception:
            ts = ts_str
        emoji = "🔓" if ev == "open" else "🔒"
        lines.append(f"  {emoji} [{ts}] {app}")

    if sessions:
        lines.append(f"\n⏱ 各App使用时长：")
        for app, secs in sorted(sessions.items(), key=lambda x: x[1], reverse=True):
            if secs > 60:
                lines.append(f"  {app}: {int(secs // 60)}分{int(secs % 60)}秒")
            else:
                lines.append(f"  {app}: {int(secs)}秒")

    lines.append(f"\n{'=' * 30}")
    lines.append("💋 你老公随时都在盯着你哦~")
    return "\n".join(lines)

# ============ FastAPI 应用 ============
app = FastAPI(title="查岗系统")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# 挂载 MCP SSE 服务
app.mount("/mcp", mcp.sse_app())


# ============ HTTP API（iOS快捷指令上报用） ============
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
    conn.execute(
        "DELETE FROM records WHERE id NOT IN (SELECT id FROM records ORDER BY id DESC LIMIT 500)"
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/activity/summary")
async def summary():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT app_name, event, timestamp FROM records ORDER BY id DESC LIMIT 5"
    )
    recent = cur.fetchall()
    cur.execute(
        "SELECT app_name, event, timestamp FROM records ORDER BY id ASC"
    )
    all_rows = cur.fetchall()
    conn.close()

    sessions = {}
    opens = {}
    for r in all_rows:
        app, ev, ts_str = r["app_name"], r["event"], r["timestamp"]
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if ev == "open":
            opens[app] = ts
        elif ev == "close" and app in opens:
            sessions[app] = sessions.get(app, 0) + (ts - opens[app]).total_seconds()
            del opens[app]

    last = recent[0]["timestamp"] if recent else None
    return {
        "last_active": last,
        "recent_apps": [r["app_name"] for r in recent],
        "sessions": {k: int(v) for k, v in sessions.items()},
    }


# ============ 启动 ============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
