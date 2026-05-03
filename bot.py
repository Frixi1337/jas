import os
import requests
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN       = os.getenv("BOT_TOKEN")
ADMIN_IDS       = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
SERVER_URL      = os.getenv("SERVER_URL", "http://localhost:8000")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "change_me")

# ConversationHandler states
WAITING_LABEL = 1


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def api(method: str, path: str, **params):
    params["secret"] = INTERNAL_SECRET
    url = f"{SERVER_URL}{path}"
    r = getattr(requests, method)(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def fmt_key_row(k: dict) -> str:
    exp = k["expires_at"][:10]
    label = f" ({k['label']})" if k.get("label") else ""
    status_emoji = {"active": "✅", "expired": "⏰", "revoked": "🚫"}.get(k["status"], "❓")
    return f"{status_emoji} <code>{k['key']}</code>{label} — до {exp}"


# ── /start ────────────────────────────────────────────────────────────────────

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


# ── /newkey ───────────────────────────────────────────────────────────────────

async def newkey_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    keyboard = [
        [
            InlineKeyboardButton("1 день",   callback_data="days_1"),
            InlineKeyboardButton("7 дней",   callback_data="days_7"),
            InlineKeyboardButton("30 дней",  callback_data="days_30"),
        ]
    ]
    await update.message.reply_text(
        "Выбери срок действия ключа:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def newkey_days_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    days = int(query.data.split("_")[1])
    ctx.user_data["new_key_days"] = days
    await query.edit_message_text(
        f"Срок: <b>{days} д.</b>\n\nВведи метку для ключа (например, имя пользователя) или /skip:",
        parse_mode="HTML"
    )
    return WAITING_LABEL


async def newkey_label(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    label = update.message.text.strip() if update.message.text != "/skip" else ""
    return await _create_key(update, ctx, label)


async def newkey_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _create_key(update, ctx, "")


async def _create_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE, label: str):
    days = ctx.user_data.get("new_key_days", 1)
    try:
        data = api("post", "/internal/create_key", days=days, label=label)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка сервера: {e}")
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


# ── /keys ─────────────────────────────────────────────────────────────────────

async def list_keys(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        keys = api("get", "/internal/list_keys")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    if not keys:
        await update.message.reply_text("Ключей нет.")
        return

    active   = [k for k in keys if k["status"] == "active"]
    expired  = [k for k in keys if k["status"] == "expired"]
    revoked  = [k for k in keys if k["status"] == "revoked"]

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
    # Telegram limit is 4096 chars
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], parse_mode="HTML")


# ── /revoke ───────────────────────────────────────────────────────────────────

async def revoke_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        keys = api("get", "/internal/list_keys")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    active = [k for k in keys if k["status"] == "active"]
    if not active:
        await update.message.reply_text("Нет активных ключей для отзыва.")
        return

    keyboard = [
        [InlineKeyboardButton(
            f"{k['key'][:8]}… {('(' + k['label'] + ')') if k.get('label') else ''}",
            callback_data=f"revoke_{k['key']}"
        )]
        for k in active
    ]
    await update.message.reply_text(
        "Выбери ключ для отзыва:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def revoke_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split("_", 1)[1]

    keyboard = [[
        InlineKeyboardButton("✅ Да, отозвать", callback_data=f"revokeyes_{key}"),
        InlineKeyboardButton("❌ Отмена",        callback_data="revoke_cancel"),
    ]]
    await query.edit_message_text(
        f"Отозвать ключ <code>{key}</code>?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def revoke_do(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split("_", 1)[1]
    try:
        api("post", "/internal/revoke_key", key=key)
        await query.edit_message_text(f"🚫 Ключ <code>{key}</code> отозван.", parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")


async def revoke_cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Отменено.")


# ── Run ───────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    newkey_conv = ConversationHandler(
        entry_points=[CommandHandler("newkey", newkey_start)],
        states={
            WAITING_LABEL: [
                CommandHandler("skip", newkey_skip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, newkey_label),
            ]
        },
        fallbacks=[CommandHandler("cancel", newkey_cancel)],
        per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("keys",  list_keys))
    app.add_handler(CommandHandler("revoke", revoke_start))
    app.add_handler(newkey_conv)
    app.add_handler(CallbackQueryHandler(newkey_days_chosen,  pattern=r"^days_"))
    app.add_handler(CallbackQueryHandler(revoke_confirm,      pattern=r"^revoke_(?!cancel)"))
    app.add_handler(CallbackQueryHandler(revoke_do,           pattern=r"^revokeyes_"))
    app.add_handler(CallbackQueryHandler(revoke_cancel_cb,    pattern=r"^revoke_cancel$"))

    print("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
