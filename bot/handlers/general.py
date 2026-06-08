import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from db.payouts import build_info_text, build_standings_text


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sold-team list + pot. Alias: /results."""
    text = await asyncio.to_thread(build_info_text)
    await update.message.reply_text(text)


async def standings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Per-owner leaderboard. Alias: /leaderboard."""
    text = await asyncio.to_thread(build_standings_text)
    await update.message.reply_text(text)


def register(app: Application):
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler(["info", "results"], info))
    app.add_handler(CommandHandler(["standings", "leaderboard"], standings))
