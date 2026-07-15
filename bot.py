import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from brew import build
from database import (
    add_subscriber,
    add_watch,
    initialise,
    remove_watch,
    subscribers,
    watchlist,
)
from sources import refresh

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Singapore")
BREW_HOUR = int(os.getenv("BREW_HOUR", "7"))
BREW_MINUTE = int(os.getenv("BREW_MINUTE", "30"))
USER_AGENT = os.getenv("USER_AGENT", "Marsad/0.1 contact@example.com")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☕ Brew", callback_data="brew")],
        [
            InlineKeyboardButton("🏢 Companies", callback_data="companies"),
            InlineKeyboardButton("📈 Markets", callback_data="markets"),
        ],
        [
            InlineKeyboardButton("🧠 Themes", callback_data="themes"),
            InlineKeyboardButton("⚙️ Watchlists", callback_data="watchlists"),
        ],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh")],
    ])


async def send(message, text, markup=None):
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=markup,
    )


async def send_brew(message):
    chunks = build(TIMEZONE)
    for index, chunk in enumerate(chunks):
        await send(message, chunk, menu() if index == len(chunks) - 1 else None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_subscriber(update.effective_chat.id)
    await send(
        update.effective_message,
        "<b>MARSAD</b>\n"
        "<i>Your personal financial observatory.</i>\n\n"
        "Tap <b>☕ Brew</b> to generate today's edition.",
        menu(),
    )


async def brew_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_brew(update.effective_message)


async def add_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    term = " ".join(context.args).strip()
    if not term:
        await send(update.effective_message, "Use: <code>/addcompany NVIDIA</code>")
        return
    result = "Added" if add_watch(term, "company") else "Already following"
    await send(update.effective_message, f"{result} <b>{term}</b>.", menu())


async def add_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    term = " ".join(context.args).strip()
    if not term:
        await send(update.effective_message, "Use: <code>/addtheme AI capex</code>")
        return
    result = "Added" if add_watch(term, "theme") else "Already following"
    await send(update.effective_message, f"{result} <b>{term}</b>.", menu())


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    term = " ".join(context.args).strip()
    result = "Removed" if remove_watch(term) else "Not found"
    await send(update.effective_message, f"{result} <b>{term}</b>.", menu())


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "brew":
        await send_brew(query.message)
    elif query.data == "refresh":
        await send(query.message, "Refreshing sources…")
        result = await refresh(USER_AGENT)
        healthy = sum(
            1 for item in result.get("source_health", [])
            if item.get("status") == "ok"
        )
        total = len(result.get("source_health", []))
        text = (
            f'Refresh complete: <b>{result["added"]}</b> new stories.\n'
            f'Direct sources healthy: <b>{healthy}/{total}</b>.'
        )
        if result["errors"]:
            text += f'\n{len(result["errors"])} source checks were unavailable.'
        await send(query.message, text, menu())
    elif query.data == "watchlists":
        companies = ", ".join(watchlist("company")) or "None"
        themes = ", ".join(watchlist("theme")) or "None"
        await send(
            query.message,
            f"<b>Companies</b>\n{companies}\n\n<b>Themes</b>\n{themes}",
            menu(),
        )
    else:
        await send(
            query.message,
            "This Terminal page is coming next. Brew is the live test feature.",
            menu(),
        )


async def scheduled_refresh(context: ContextTypes.DEFAULT_TYPE):
    result = await refresh(USER_AGENT)
    logger.info("Refresh result: %s", result)


async def scheduled_brew(context: ContextTypes.DEFAULT_TYPE):
    chunks = build(TIMEZONE)
    for chat_id in subscribers():
        try:
            for index, chunk in enumerate(chunks):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=menu() if index == len(chunks) - 1 else None,
                )
        except Exception:
            logger.exception("Could not send Brew to %s", chat_id)


def seed():
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    for company in config.get("default_companies", []):
        add_watch(company, "company")
    for theme in config.get("default_themes", []):
        add_watch(theme, "theme")


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

    initialise()
    seed()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("brew", brew_command))
    app.add_handler(CommandHandler("addcompany", add_company))
    app.add_handler(CommandHandler("addtheme", add_theme))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CallbackQueryHandler(callback))

    app.job_queue.run_repeating(scheduled_refresh, interval=1800, first=5)

    timezone = ZoneInfo(TIMEZONE)
    send_time = datetime.now(timezone).replace(
        hour=BREW_HOUR,
        minute=BREW_MINUTE,
        second=0,
        microsecond=0,
    ).timetz()
    app.job_queue.run_daily(scheduled_brew, time=send_time)

    logger.info(
        "Marsad started. Brew scheduled for %02d:%02d %s",
        BREW_HOUR,
        BREW_MINUTE,
        TIMEZONE,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
