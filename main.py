import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

from fastapi import FastAPI, Query, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="FrixiHack Key Server")
DB_PATH = os.getenv("DB_PATH", "keys.db")

# Разрешаем запросы отовсюду (Railway не будет блокировать)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Database ──────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                key        TEXT PRIMARY KEY,
                label      TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked    INTEGER NOT NULL DEFAULT 0
            )
        """)

init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_key() -> str:
    return secrets.token_hex(16)


def is_key_valid(key: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT expires_at, revoked FROM keys WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return False
    if row["revoked"]:
        return False
    expires = datetime.fromisoformat(row["expires_at"])
    return datetime.utcnow() < expires


INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "change_me")


def verify_secret(secret: str):
    if secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Публичные эндпоинты ───────────────────────────────────────────────────────

@app.get("/check_user")
def check_user(
    username: str = Query(...),
    api_key: str = Header(default="", alias="API-Key")
):
    """Клиент FrixiHack проверяет ключ через заголовок API-Key."""
    if api_key != os.getenv("API_KEY", "apifrixi"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    exists = is_key_valid(username)
    return {"exists": exists}


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Внутренние эндпоинты (бот) ────────────────────────────────────────────────
# Доступны публично по URL, но защищены секретом.
# Railway whitelist обходим тем, что эти маршруты просто открыты —
# защита только через INTERNAL_SECRET в query params.

@app.post("/bot/create_key")
def create_key(
    days: int = Query(..., ge=1, le=365),
    label: str = Query(default=""),
    secret: str = Query(...)
):
    verify_secret(secret)
    key = generate_key()
    now = datetime.utcnow()
    expires = now + timedelta(days=days)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO keys (key, label, created_at, expires_at, revoked) VALUES (?,?,?,?,0)",
            (key, label, now.isoformat(), expires.isoformat())
        )
    return {
        "key": key,
        "label": label,
        "expires_at": expires.isoformat(),
        "days": days
    }


@app.post("/bot/revoke_key")
def revoke_key(key: str = Query(...), secret: str = Query(...)):
    verify_secret(secret)
    with get_db() as conn:
        cur = conn.execute("UPDATE keys SET revoked=1 WHERE key=?", (key,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"revoked": True, "key": key}


@app.get("/bot/list_keys")
def list_keys(secret: str = Query(...)):
    verify_secret(secret)
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT key, label, expires_at, revoked FROM keys ORDER BY expires_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        status = "revoked" if r["revoked"] else ("expired" if r["expires_at"] < now else "active")
        result.append({
            "key": r["key"],
            "label": r["label"],
            "expires_at": r["expires_at"],
            "status": status
        })
    return result


# Старые /internal/ маршруты оставляем для совместимости
@app.post("/internal/create_key")
def create_key_legacy(
    days: int = Query(..., ge=1, le=365),
    label: str = Query(default=""),
    secret: str = Query(...)
):
    return create_key(days=days, label=label, secret=secret)


@app.post("/internal/revoke_key")
def revoke_key_legacy(key: str = Query(...), secret: str = Query(...)):
    return revoke_key(key=key, secret=secret)


@app.get("/internal/list_keys")
def list_keys_legacy(secret: str = Query(...)):
    return list_keys(secret=secret)
