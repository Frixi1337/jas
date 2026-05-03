import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN       = os.getenv("BOT_TOKEN")
ADMIN_IDS       = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
# Внутри Railway используем внутренний адрес сервиса (не публичный домен)
# Формат: http://НАЗВАНИЕ_СЕРВИСА.railway.internal:PORT
# Если не задан — фоллбэк на публичный URL
SERVER_INTERNAL = os.getenv("SERVER_INTERNAL_URL", "")
SERVER_PUBLIC   = os.getenv("API_BASE_URL", "https://jas-production.up.railway.app")
SERVER_URL      = SERVER_INTERNAL if SERVER_INTERNAL else SERVER_PUBLIC
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "apifrixi")

logger.info(f"ADMIN_IDS: {ADMIN_IDS}")
logger.info(f"SERVER_URL (effective): {SERVER_URL}")

CHOOSING_DAYS = 0
WAITING_LABEL = 1


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def api_get(path: str, **params) -> dict:
    params["secret"] = INTERNAL_SECRET
    url = f"{SERVER_URL}{path}"
    logger.info(f"GET {url}")
    r = requests.get(url, params=params, timeout=10)
    logger.info(f"← {r.status_code} {r.text[:200]}")
    r.raise_for_status()
    return r.json()


def api_post(path: str, **params) -> dict:
    params["secret"] = INTERNAL_SECRET
    url = f"{SERVER_URL}{path}"
    logger.info(f"POST {url}")
    r = requests.post(url, params=params, timeout=10)
    logger.info(f"← {r.status_code} {r.text[:200]}")
    r.raise_for_status()
    return r.json()


def fmt_key_row(k: dict) -> str:
    exp = k["expires_at"][:10]
    label = f" ({k['label']})" if k.get("label") else ""
    emoji = {"active": "✅", "expired": "⏰", "revoked": "🚫"}.get(k["status"], "❓")
    return f"{emoji} <code>{k['key']}</code>{label} — до {exp}"


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    await update.message.reply_text(
        "🔑 <b>FrixiHack Key Manager</b>\n\n"
        "/newkey — создать ключ\n"
        "/keys — список ключей\n"
        "/revoke — отозвать ключ",
        parse_mode="HTML"
    )


async def newkey_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    keyboard = [[
        InlineKeyboardButton("1 день",  callback_data="days_1"),
        InlineKeyboardButton("7 дней",  callback_data="days_7"),
        InlineKeyboardButton("30 дней", callback_data="days_30"),
    ]]
    await update.message.reply_text(
        "Выбери срок действия ключа:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_DAYS


async def newkey_days_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    days = int(query.data.split("_")[1])
    ctx.user_data["new_key_days"] = days
    await query.message.reply_text(
        f"Срок: <b>{days} д.</b>\n\nВведи метку (имя пользователя) или /skip:",
        parse_mode="HTML"
    )
    return WAITING_LABEL


async def newkey_label(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _create_key(update, ctx, update.message.text.strip())


async def newkey_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _create_key(update, ctx, "")


async def _create_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE, label: str):
    days = ctx.user_data.get("new_key_days")
    if not days:
        await update.message.reply_text("❌ Потерян срок. Начни заново: /newkey")
        return ConversationHandler.END
    try:
        data = api_post("/internal/create_key", days=days, label=label)
    except requests.HTTPError as e:
        await update.message.reply_text(
            f"❌ Сервер: <code>{e.response.status_code}: {e.response.text}</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    except requests.ConnectionError as e:
        await update.message.reply_text(
            f"❌ Нет соединения с сервером.\n<code>{e}</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
        return ConversationHandler.END

    exp = data["expires_at"][:10]
    label_str = f"\n📝 Метка: <b>{label}</b>" if label else ""
    await update.message.reply_text(
        f"✅ Ключ создан!\n\n"
        f"🔑 <code>{data['key']}</code>{label_str}\n"
        f"⏳ Срок: <b>{days} д.</b> (до {exp})",
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def newkey_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def list_keys(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        keys = api_get("/internal/list_keys")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
        return
    if not keys:
        await update.message.reply_text("Ключей нет.")
        return
    active  = [k for k in keys if k["status"] == "active"]
    expired = [k for k in keys if k["status"] == "expired"]
    revoked = [k for k in keys if k["status"] == "revoked"]
    lines = ["🗂 <b>Все ключи:</b>\n"]
    if active:
        lines.append("✅ <b>Активные:</b>")
        lines += [fmt_key_row(k) for k in active]
    if expired:
        lines.append("\n⏰ <b>Истёкшие:</b>")
        lines += [fmt_key_row(k) for k in expired]
    if revoked:
        lines.append("\n🚫 <b>Отозванные:</b>")
        lines += [fmt_key_row(k) for k in revoked]
    text = "\n".join(lines)
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], parse_mode="HTML")


async def revoke_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        keys = api_get("/internal/list_keys")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
        return
    active = [k for k in keys if k["status"] == "active"]
    if not active:
        await update.message.reply_text("Нет активных ключей.")
        return
    keyboard = [
        [InlineKeyboardButton(
            f"{k['key'][:8]}…{(' (' + k['label'] + ')') if k.get('label') else ''}",
            callback_data=f"rk_{k['key']}"
        )] for k in active
    ]
    await update.message.reply_text("Выбери ключ для отзыва:", reply_markup=InlineKeyboardMarkup(keyboard))


async def revoke_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data[len("rk_"):]
    keyboard = [[
        InlineKeyboardButton("✅ Да, отозвать", callback_data=f"rkyes_{key}"),
        InlineKeyboardButton("❌ Отмена",        callback_data="rkcancel"),
    ]]
    await query.edit_message_text(
        f"Отозвать ключ <code>{key}</code>?",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
    )


async def revoke_do(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data[len("rkyes_"):]
    try:
        api_post("/internal/revoke_key", key=key)
        await query.edit_message_text(f"🚫 Ключ <code>{key}</code> отозван.", parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")


async def revoke_cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Отменено.")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    newkey_conv = ConversationHandler(
        entry_points=[CommandHandler("newkey", newkey_start)],
        states={
            CHOOSING_DAYS: [CallbackQueryHandler(newkey_days_chosen, pattern=r"^days_\d+$")],
            WAITING_LABEL: [
                CommandHandler("skip", newkey_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, newkey_label),
            ],
        },
        fallbacks=[CommandHandler("cancel", newkey_cancel)],
    )
    app.add_handler(newkey_conv)
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("keys",   list_keys))
    app.add_handler(CommandHandler("revoke", revoke_start))
    app.add_handler(CallbackQueryHandler(revoke_confirm,   pattern=r"^rk_"))
    app.add_handler(CallbackQueryHandler(revoke_do,        pattern=r"^rkyes_"))
    app.add_handler(CallbackQueryHandler(revoke_cancel_cb, pattern=r"^rkcancel$"))
    logger.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
