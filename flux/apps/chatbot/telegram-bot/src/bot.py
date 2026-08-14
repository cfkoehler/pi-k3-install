import logging
import os

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("chatbot-telegram-bot")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ROUTER_BASE_URL = os.environ["ROUTER_BASE_URL"].rstrip("/")
ROUTER_API_KEY = os.environ["ROUTER_API_KEY"]
ALLOWED_CHAT_IDS = {
    int(chat_id) for chat_id in os.environ["TELEGRAM_ALLOWED_IDS"].split(",") if chat_id.strip()
}

# TODO(connor): replace with the real model aliases your router exposes.
MODEL_ALIASES = {
    "default": "auto",
}

HISTORY_LIMIT = 20  # messages kept per chat; in-memory only, lost on restart

conversations: dict[int, list[dict]] = {}


def is_allowed(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS


async def call_router(chat_id: int, model: str, user_text: str) -> str:
    history = conversations.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    del history[:-HISTORY_LIMIT]

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{ROUTER_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {ROUTER_API_KEY}"},
            json={"model": model, "messages": history},
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]

    history.append({"role": "assistant", "content": reply})
    del history[:-HISTORY_LIMIT]
    return reply


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_allowed(chat_id):
        return

    try:
        reply = await call_router(chat_id, "auto", update.message.text)
    except Exception:
        logger.exception("router request failed for chat %s", chat_id)
        await update.message.reply_text("Sorry, the router request failed. Try again later.")
        return

    await update.message.reply_text(reply)


async def handle_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_allowed(chat_id):
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /model <alias> <message>")
        return

    alias, user_text = context.args[0], " ".join(context.args[1:])
    model = MODEL_ALIASES.get(alias)
    if model is None:
        await update.message.reply_text(f"Unknown alias '{alias}'. See /models for the list.")
        return

    try:
        reply = await call_router(chat_id, model, user_text)
    except Exception:
        logger.exception("router request failed for chat %s", chat_id)
        await update.message.reply_text("Sorry, the router request failed. Try again later.")
        return

    await update.message.reply_text(reply)


async def handle_models_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not is_allowed(chat_id):
        return

    lines = [f"{alias} -> {model}" for alias, model in MODEL_ALIASES.items()]
    await update.message.reply_text("Known aliases:\n" + "\n".join(lines))


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("model", handle_model_command))
    app.add_handler(CommandHandler("models", handle_models_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
