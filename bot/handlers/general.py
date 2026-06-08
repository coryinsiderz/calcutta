import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import db.queries as queries


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")


async def results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teams = await asyncio.to_thread(queries.get_results)
    if not teams:
        await update.message.reply_text("No teams sold yet.")
        return

    lines = ["🏆 *Auction Results*\n"]
    for t in teams:
        lines.append(f"{t['flag']} {t['name']} → @{t['sold_to_username']} — ${t['sold_price']:,}")

    total_pot = sum(t["sold_price"] or 0 for t in teams)
    lines.append(f"\n*Pot: ${total_pot:,}*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def register(app: Application):
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("results", results))
