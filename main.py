"""
PromoAi License Key Server
- POST /check_user   — клиент проверяет ключ
- GET  /admin        — панель управления (логин: frixi / Popuslol)
"""

import os, json, uuid, secrets, hashlib, hmac
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import bcrypt
from flask import (Flask, request, jsonify, session,
                   redirect, url_for, render_template_string, abort)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ──────────────────────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────────────────────
ADMIN_USERNAME = "frixi"

# Хэш пароля "Popuslol" — bcrypt 12 раундов
# Чтобы сгенерировать новый: python -c "import bcrypt; print(bcrypt.hashpw(b'ПАРОЛЬ', bcrypt.gensalt(12)).decode())"
_PASS_ENV = os.environ.get("ADMIN_PASSWORD_HASH", "").encode()
if _PASS_ENV:
    ADMIN_PASSWORD_HASH = _PASS_ENV
else:
    # Генерируем при первом старте, храним в памяти
    ADMIN_PASSWORD_HASH = bcrypt.hashpw(b"Popuslol", bcrypt.gensalt(12))

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
KEYS_FILE  = Path(os.environ.get("KEYS_FILE", "keys.txt"))
KEY_DAYS   = 30

# ──────────────────────────────────────────────────────────────
#  APP
# ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)

# ──────────────────────────────────────────────────────────────
#  KEY STORAGE  (keys.txt — JSON-массив)
# ──────────────────────────────────────────────────────────────
def _load() -> list:
    if not KEYS_FILE.exists():
        return []
    try:
        return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save(data: list):
    KEYS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _expired(entry: dict) -> bool:
    try:
        exp = datetime.fromisoformat(entry["expires_at"])
        return datetime.now(timezone.utc) > exp
    except Exception:
        return True

def _sanitize(s: str, max_len=128) -> str:
    """Убираем всё лишнее — защита от инъекций в JSON-хранилище."""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_. ")
    return "".join(c for c in str(s) if c in allowed)[:max_len]

def generate_key() -> str:
    """PROMO-XXXX-XXXX-XXXX-XXXX"""
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    return "PROMO-" + "-".join(parts)

def create_key(note: str = "") -> dict:
    entry = {
        "key":          generate_key(),
        "note":         _sanitize(note, 64),
        "created_at":   _now(),
        "expires_at":   (datetime.now(timezone.utc) + timedelta(days=KEY_DAYS)).isoformat(),
        "activated_at": None,
        "device_ip":    None,
        "revoked":      False,
    }
    data = _load()
    data.append(entry)
    _save(data)
    return entry

def find_key(key: str) -> dict | None:
    key = _sanitize(key.upper(), 30)
    for e in _load():
        if e["key"] == key:
            return e
    return None

def revoke_key(key: str) -> bool:
    key = _sanitize(key.upper(), 30)
    data = _load()
    changed = False
    for e in data:
        if e["key"] == key and not e["revoked"]:
            e["revoked"] = True
            changed = True
    if changed:
        _save(data)
    return changed

def activate_key(key: str, ip: str) -> dict:
    """Привязывает IP к ключу при первом использовании."""
    key = _sanitize(key.upper(), 30)
    ip  = _sanitize(ip, 45)
    data = _load()
    for e in data:
        if e["key"] == key:
            if e["device_ip"] is None:
                e["device_ip"]    = ip
                e["activated_at"] = _now()
            _save(data)
            return e
    return None

# ──────────────────────────────────────────────────────────────
#  AUTH DECORATOR
# ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

def _csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]

def _verify_csrf(token: str) -> bool:
    return hmac.compare_digest(session.get("csrf", ""), token)

# ──────────────────────────────────────────────────────────────
#  API  —  /check_user  (вызывается клиентом)
# ──────────────────────────────────────────────────────────────
@app.route("/check_user", methods=["GET"])
@limiter.limit("30 per minute")
def check_user():
    raw_key = request.args.get("username", "").strip()
    if not raw_key:
        return jsonify({"exists": False}), 400

    key = _sanitize(raw_key.upper(), 30)
    entry = find_key(key)

    if entry is None or entry["revoked"] or _expired(entry):
        return jsonify({"exists": False})

    # Привязка устройства (по IP)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    entry = activate_key(key, ip)

    if entry is None:
        return jsonify({"exists": False})

    # Проверяем что IP совпадает
    if entry["device_ip"] and entry["device_ip"] != ip:
        return jsonify({"exists": False})

    return jsonify({"exists": True})


# Совместимость с оригинальным клиентом (дополнительные эндпоинты)
@app.route("/get_brawler_list")
def get_brawler_list():
    return jsonify([])

@app.route("/get_brawler_info")
def get_brawler_info():
    return jsonify({})

@app.route("/check_version")
def check_version():
    return jsonify({"latest": "0.8.1"})

@app.route("/get_discord_link")
def get_discord_link():
    return jsonify({"link": "https://t.me/promo_bs"})

@app.route("/get_wall_model_hash")
def get_wall_model_hash():
    return jsonify({"hash": ""})

@app.route("/get_wall_model_classes")
def get_wall_model_classes():
    return jsonify([])

# ──────────────────────────────────────────────────────────────
#  ADMIN  —  LOGIN
# ──────────────────────────────────────────────────────────────
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>PromoAi — Вход</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#060606;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:'Rajdhani',sans-serif;overflow:hidden}
.grid{position:fixed;inset:0;background-image:linear-gradient(rgba(180,0,0,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(180,0,0,.06) 1px,transparent 1px);background-size:40px 40px;pointer-events:none}
.glow{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:600px;height:300px;background:radial-gradient(ellipse,rgba(200,0,0,.15) 0%,transparent 70%);pointer-events:none;animation:pulse 3s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.5;transform:translate(-50%,-50%) scale(1)}50%{opacity:1;transform:translate(-50%,-50%) scale(1.1)}}
.card{position:relative;background:rgba(10,0,0,.9);border:1px solid #2a0000;border-radius:16px;padding:44px 48px;width:400px;box-shadow:0 0 60px rgba(200,0,0,.1)}
.card::before{content:'';position:absolute;inset:0;border-radius:16px;background:linear-gradient(135deg,rgba(200,0,0,.05),transparent 60%);pointer-events:none}
.logo{text-align:center;margin-bottom:32px}
.logo-text{font-size:32px;font-weight:700;letter-spacing:4px;color:#fff;text-shadow:0 0 20px rgba(200,0,0,.5)}
.logo-dot{color:#cc0000}
.sub{font-family:'Share Tech Mono',monospace;font-size:11px;color:#333;letter-spacing:2px;text-align:center;margin-top:4px}
label{display:block;font-size:12px;letter-spacing:2px;color:#555;margin-bottom:6px;text-transform:uppercase}
input{width:100%;background:#0e0000;border:1px solid #2a0000;border-radius:8px;padding:12px 16px;color:#fff;font-family:'Share Tech Mono',monospace;font-size:14px;outline:none;transition:border-color .2s}
input:focus{border-color:#880000;box-shadow:0 0 0 3px rgba(200,0,0,.08)}
.field{margin-bottom:20px}
.btn{width:100%;background:#cc0000;border:none;border-radius:8px;padding:14px;color:#fff;font-family:'Rajdhani',sans-serif;font-size:16px;font-weight:700;letter-spacing:2px;cursor:pointer;transition:all .2s;margin-top:8px;text-transform:uppercase}
.btn:hover{background:#ff1a1a;box-shadow:0 0 20px rgba(200,0,0,.4)}
.err{background:rgba(200,0,0,.1);border:1px solid #440000;border-radius:8px;padding:10px 14px;font-size:13px;color:#ff4444;margin-bottom:16px;text-align:center}
.tg{display:block;text-align:center;margin-top:20px;font-size:11px;color:#222;text-decoration:none;letter-spacing:1px;transition:color .2s}
.tg:hover{color:#cc0000}
</style>
</head>
<body>
<div class="grid"></div>
<div class="glow"></div>
<div class="card">
  <div class="logo">
    <div class="logo-text"><span class="logo-dot">⬤</span> PROMOAI <span class="logo-dot">⬤</span></div>
    <div class="sub">// KEY MANAGEMENT SYSTEM //</div>
  </div>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="POST" action="/admin/login">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <div class="field">
      <label>Логин</label>
      <input type="text" name="username" autocomplete="username" required>
    </div>
    <div class="field">
      <label>Пароль</label>
      <input type="password" name="password" autocomplete="current-password" required>
    </div>
    <button class="btn" type="submit">Войти</button>
  </form>
  <a class="tg" href="https://t.me/promo_bs" target="_blank">t.me/promo_bs</a>
</div>
</body></html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>PromoAi — Панель</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#060606;color:#ccc;font-family:'Rajdhani',sans-serif;min-height:100vh}
.grid{position:fixed;inset:0;background-image:linear-gradient(rgba(180,0,0,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(180,0,0,.04) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}
.wrap{position:relative;z-index:1;max-width:1100px;margin:0 auto;padding:32px 24px}

/* HEADER */
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;border-bottom:1px solid #1a0000;padding-bottom:20px}
.logo{font-size:22px;font-weight:700;letter-spacing:4px;color:#fff}
.logo span{color:#cc0000}
.logout{font-family:'Share Tech Mono',monospace;font-size:12px;color:#444;text-decoration:none;letter-spacing:1px;padding:6px 12px;border:1px solid #1a0000;border-radius:6px;transition:all .2s}
.logout:hover{color:#cc0000;border-color:#440000}

/* STATS */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}
.stat{background:rgba(10,0,0,.8);border:1px solid #1a0000;border-radius:12px;padding:18px 20px}
.stat-n{font-size:28px;font-weight:700;color:#fff}
.stat-n.red{color:#cc0000}
.stat-n.green{color:#22cc55}
.stat-n.yellow{color:#cc8800}
.stat-l{font-size:11px;letter-spacing:2px;color:#444;text-transform:uppercase;margin-top:2px;font-family:'Share Tech Mono',monospace}

/* CREATE */
.create-box{background:rgba(10,0,0,.8);border:1px solid #1a0000;border-radius:12px;padding:24px;margin-bottom:28px}
.box-title{font-size:14px;letter-spacing:3px;color:#555;text-transform:uppercase;margin-bottom:16px;font-family:'Share Tech Mono',monospace}
.create-row{display:flex;gap:12px;align-items:center}
.inp{background:#0e0000;border:1px solid #2a0000;border-radius:8px;padding:10px 14px;color:#fff;font-family:'Share Tech Mono',monospace;font-size:13px;outline:none;flex:1;transition:border-color .2s}
.inp:focus{border-color:#880000}
.btn{background:#cc0000;border:none;border-radius:8px;padding:10px 22px;color:#fff;font-family:'Rajdhani',sans-serif;font-weight:700;font-size:14px;letter-spacing:2px;cursor:pointer;transition:all .2s;text-transform:uppercase}
.btn:hover{background:#ff1a1a;box-shadow:0 0 16px rgba(200,0,0,.3)}
.btn.gray{background:#1a0000;color:#666}
.btn.gray:hover{background:#2a0000;color:#ccc;box-shadow:none}

{% if flash %}
.flash{background:rgba(0,180,0,.08);border:1px solid #004400;border-radius:8px;padding:10px 16px;margin-bottom:20px;font-size:14px;color:#22cc55;font-family:'Share Tech Mono',monospace}
{% endif %}

/* TABLE */
.table-wrap{background:rgba(10,0,0,.8);border:1px solid #1a0000;border-radius:12px;overflow:hidden}
.t-header{display:grid;grid-template-columns:2fr 1.2fr 1.2fr 1fr 1fr 0.8fr;gap:0;padding:12px 20px;background:#0e0000;border-bottom:1px solid #1a0000}
.t-header span{font-size:10px;letter-spacing:2px;color:#444;text-transform:uppercase;font-family:'Share Tech Mono',monospace}
.row{display:grid;grid-template-columns:2fr 1.2fr 1.2fr 1fr 1fr 0.8fr;gap:0;padding:14px 20px;border-bottom:1px solid #0d0000;transition:background .15s;align-items:center}
.row:last-child{border-bottom:none}
.row:hover{background:rgba(200,0,0,.03)}
.key-val{font-family:'Share Tech Mono',monospace;font-size:13px;color:#fff;letter-spacing:1px}
.meta{font-size:12px;color:#444;font-family:'Share Tech Mono',monospace}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase}
.badge.active{background:rgba(0,180,0,.1);color:#22cc55;border:1px solid #004400}
.badge.expired{background:rgba(100,100,0,.1);color:#888800;border:1px solid #333300}
.badge.revoked{background:rgba(180,0,0,.1);color:#cc0000;border:1px solid #440000}
.badge.pending{background:rgba(0,100,180,.1);color:#4488cc;border:1px solid #002244}
.rev-btn{background:transparent;border:1px solid #2a0000;border-radius:6px;padding:4px 10px;color:#555;font-size:11px;cursor:pointer;font-family:'Share Tech Mono',monospace;transition:all .2s;letter-spacing:1px}
.rev-btn:hover{background:#1a0000;color:#cc0000;border-color:#440000}
.empty{padding:40px;text-align:center;color:#2a0000;font-family:'Share Tech Mono',monospace;font-size:13px;letter-spacing:2px}
.note-val{font-size:12px;color:#555;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style>
</head>
<body>
<div class="grid"></div>
<div class="wrap">

  <div class="header">
    <div class="logo"><span>⬤</span> PROMOAI <span>⬤</span> <span style="font-size:13px;color:#333;letter-spacing:2px">KEY PANEL</span></div>
    <a class="logout" href="/admin/logout">[ ВЫЙТИ ]</a>
  </div>

  {% if flash %}<div class="flash">✓ {{ flash }}</div>{% endif %}

  <div class="stats">
    <div class="stat"><div class="stat-n">{{ total }}</div><div class="stat-l">Всего ключей</div></div>
    <div class="stat"><div class="stat-n green">{{ active }}</div><div class="stat-l">Активных</div></div>
    <div class="stat"><div class="stat-n yellow">{{ pending }}</div><div class="stat-l">Не активированы</div></div>
    <div class="stat"><div class="stat-n red">{{ revoked }}</div><div class="stat-l">Отозванных</div></div>
  </div>

  <div class="create-box">
    <div class="box-title">// Создать ключ</div>
    <form method="POST" action="/admin/create">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <div class="create-row">
        <input class="inp" type="text" name="note" placeholder="Заметка (необязательно)" maxlength="64">
        <button class="btn" type="submit">+ Создать ключ</button>
      </div>
    </form>
  </div>

  <div class="table-wrap">
    <div class="t-header">
      <span>Ключ</span>
      <span>Истекает</span>
      <span>IP устройства</span>
      <span>Заметка</span>
      <span>Статус</span>
      <span>Действие</span>
    </div>
    {% if keys %}
      {% for k in keys %}
      <div class="row">
        <div class="key-val">{{ k.key }}</div>
        <div class="meta">{{ k.expires_at[:10] }}</div>
        <div class="meta">{{ k.device_ip or '—' }}</div>
        <div class="note-val" title="{{ k.note }}">{{ k.note or '—' }}</div>
        <div>
          {% if k.revoked %}
            <span class="badge revoked">Отозван</span>
          {% elif k.expired %}
            <span class="badge expired">Истёк</span>
          {% elif k.device_ip %}
            <span class="badge active">Активен</span>
          {% else %}
            <span class="badge pending">Ожидание</span>
          {% endif %}
        </div>
        <div>
          {% if not k.revoked and not k.expired %}
          <form method="POST" action="/admin/revoke" style="display:inline" onsubmit="return confirm('Отозвать ключ?')">
            <input type="hidden" name="csrf" value="{{ csrf }}">
            <input type="hidden" name="key" value="{{ k.key }}">
            <button class="rev-btn" type="submit">Отозвать</button>
          </form>
          {% else %}
            <span style="color:#1a0000;font-size:11px;font-family:'Share Tech Mono',monospace">—</span>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    {% else %}
      <div class="empty">// НЕТ КЛЮЧЕЙ — СОЗДАЙТЕ ПЕРВЫЙ</div>
    {% endif %}
  </div>

</div>
</body></html>
"""

# ──────────────────────────────────────────────────────────────
#  ADMIN ROUTES
# ──────────────────────────────────────────────────────────────
@app.route("/admin")
@app.route("/admin/")
def admin_login():
    if session.get("admin"):
        return redirect(url_for("dashboard"))
    return render_template_string(LOGIN_HTML, error=None, csrf=_csrf_token())

@app.route("/admin/login", methods=["POST"])
@limiter.limit("10 per minute")
def admin_login_post():
    csrf = request.form.get("csrf", "")
    if not _verify_csrf(csrf):
        abort(403)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").encode()

    if (hmac.compare_digest(username, ADMIN_USERNAME)
            and bcrypt.checkpw(password, ADMIN_PASSWORD_HASH)):
        session["admin"] = True
        session.permanent = True
        return redirect(url_for("dashboard"))

    return render_template_string(LOGIN_HTML,
                                  error="Неверный логин или пароль",
                                  csrf=_csrf_token())

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin/dashboard")
@login_required
def dashboard():
    raw_keys = _load()

    # Добавляем флаг expired для шаблона
    display = []
    for k in reversed(raw_keys):  # новые сверху
        entry = dict(k)
        entry["expired"] = _expired(k) and not k["revoked"]
        display.append(entry)

    total   = len(raw_keys)
    active  = sum(1 for k in raw_keys if not k["revoked"] and not _expired(k) and k["device_ip"])
    pending = sum(1 for k in raw_keys if not k["revoked"] and not _expired(k) and not k["device_ip"])
    revoked = sum(1 for k in raw_keys if k["revoked"])

    flash = session.pop("flash", None)

    return render_template_string(DASHBOARD_HTML,
                                  keys=display,
                                  total=total,
                                  active=active,
                                  pending=pending,
                                  revoked=revoked,
                                  flash=flash,
                                  csrf=_csrf_token())

@app.route("/admin/create", methods=["POST"])
@login_required
def admin_create():
    if not _verify_csrf(request.form.get("csrf", "")):
        abort(403)
    note = request.form.get("note", "")
    entry = create_key(note)
    session["flash"] = f"Ключ создан: {entry['key']}"
    return redirect(url_for("dashboard"))

@app.route("/admin/revoke", methods=["POST"])
@login_required
def admin_revoke():
    if not _verify_csrf(request.form.get("csrf", "")):
        abort(403)
    key = request.form.get("key", "")
    if revoke_key(key):
        session["flash"] = f"Ключ отозван: {key}"
    return redirect(url_for("dashboard"))

# ──────────────────────────────────────────────────────────────
#  HEALTH CHECK
# ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "PromoAi Key Server"})

# ──────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
