import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)


async def cmd_bid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    engine = context.bot_data["engine"]

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /bid <amount>")
        return

    raw = args[0].lstrip("$").replace(",", "")
    if not raw.isdigit():
        await update.message.reply_text("Amount must be a whole number.  e.g. /bid 50")
        return

    amount = int(raw)
    user = update.effective_user
    username = user.username or user.first_name

    accepted, reason = await engine.process_bid(user.id, username, amount)

    if not accepted:
        await update.message.reply_text(f"Bid rejected: {reason}")
    # On accept, the engine posts the "$X — @user" confirmation; the /bid
    # message is left in place (bot never deletes messages).


async def bid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    engine = context.bot_data["engine"]

    try:
        _, team_id_str, amount_str = query.data.split(":")
        team_id = int(team_id_str)
        amount = int(amount_str)
    except (ValueError, AttributeError):
        await query.answer("Invalid button data.", show_alert=True)
        return

    # Reject stale buttons from a previously auctioned team
    if not engine.current_team or engine.current_team["id"] != team_id:
        await query.answer("This team has already been sold!", show_alert=True)
        return

    user = query.from_user
    username = user.username or user.first_name

    await engine.process_bid(user.id, username, amount, callback_query=query)


def register(app: Application):
    app.add_handler(CommandHandler("bid", cmd_bid))
    app.add_handler(CallbackQueryHandler(bid_callback, pattern=r"^bid:\d+:\d+$"))
