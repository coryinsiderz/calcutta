import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import db.queries as queries

logger = logging.getLogger(__name__)


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    admin_ids: list[int] = context.bot_data.get("admin_ids", [])
    return update.effective_user.id in admin_ids


async def _require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not _is_admin(update, context):
        await update.message.reply_text("Not authorized.")
        return False
    return True


# ── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    engine = context.bot_data["engine"]

    if engine.status == "running":
        await update.message.reply_text("Auction is already running.")
        return
    if engine.status == "done":
        await update.message.reply_text("Auction is done. Reset the DB to start fresh.")
        return

    await update.message.reply_text("Starting auction...")
    await engine.start_auction(update.effective_chat.id)


# ── /pause / /resume ─────────────────────────────────────────────────────────

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    engine = context.bot_data["engine"]
    if engine.status != "running":
        await update.message.reply_text(f"Can't pause — status is '{engine.status}'.")
        return
    await engine.pause()
    await update.message.reply_text("⏸ Auction paused.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    engine = context.bot_data["engine"]
    if engine.status != "paused":
        await update.message.reply_text(f"Can't resume — status is '{engine.status}'.")
        return
    await engine.resume()
    await update.message.reply_text("▶️ Auction resumed.")


# ── /next ─────────────────────────────────────────────────────────────────────

async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    engine = context.bot_data["engine"]
    if engine.status not in ("running", "paused"):
        await update.message.reply_text("No active auction to advance.")
        return
    await engine.next_team()


# ── /undo ─────────────────────────────────────────────────────────────────────

async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    engine = context.bot_data["engine"]
    ok, result = await engine.undo_last_sold()
    if ok:
        await update.message.reply_text(
            f"↩️ Undo! Re-auctioning {result}.\n"
            f"Opening bid: /bid <amount>  (min ${engine.config.get('opening_floor', 1)})"
        )
    else:
        await update.message.reply_text(f"Undo failed: {result}")


# ── /correct ──────────────────────────────────────────────────────────────────

async def cmd_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /correct <amount>  — corrects the last sold team's price."""
    if not await _require_admin(update, context):
        return

    args = context.args
    if not args or not args[0].lstrip("$").isdigit():
        await update.message.reply_text("Usage: /correct <amount>  (corrects last sold team's price)")
        return

    amount = int(args[0].lstrip("$"))
    last = await asyncio.to_thread(queries.get_last_sold_team)
    if not last:
        await update.message.reply_text("No teams sold yet.")
        return

    await asyncio.to_thread(queries.correct_sold_price, last["id"], amount)
    await update.message.reply_text(
        f"✏️ Corrected: {last['flag']} {last['name']} → ${amount:,}  (was ${last['sold_price']:,})"
    )


# ── /reset ────────────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /reset CONFIRM  — wipes all bids/sales, resets to idle, reshuffles."""
    if not await _require_admin(update, context):
        return

    args = context.args
    if not args or args[0] != "CONFIRM":
        await update.message.reply_text(
            "⚠️ This wipes ALL bids and sold teams and resets the auction to idle.\n"
            "Nothing is recoverable. To confirm, send:\n\n/reset CONFIRM"
        )
        return

    engine = context.bot_data["engine"]
    await engine.reset()
    await update.message.reply_text(
        "🧹 Auction reset. All 48 teams pending, draw reshuffled, status idle.\nRun /start to begin."
    )


# ── /shuffle ──────────────────────────────────────────────────────────────────

async def cmd_shuffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    engine = context.bot_data["engine"]
    if engine.status == "running":
        await update.message.reply_text("Can't shuffle while auction is running.")
        return
    await asyncio.to_thread(queries.shuffle_pending_teams)
    await update.message.reply_text("Teams reshuffled.")


# ── /config ───────────────────────────────────────────────────────────────────

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return

    cfg = await asyncio.to_thread(queries.get_auction_config)
    bands = await asyncio.to_thread(queries.get_increment_bands)

    band_text = "\n".join(f"  ${b['min_price']}+  →  +${b['increment']}" for b in bands)
    msg = (
        f"*Auction config*\n"
        f"Going once after: {cfg['silence_once_sec']}s\n"
        f"Going twice after: {cfg['silence_twice_sec']}s\n"
        f"Sold after: {cfg['silence_sold_sec']}s\n"
        f"Opening floor: ${cfg['opening_floor']}\n\n"
        f"*Increment bands*\n{band_text}\n\n"
        f"Edit at the web panel."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    engine = context.bot_data["engine"]
    sold = await asyncio.to_thread(queries.count_sold_teams)
    pending = await asyncio.to_thread(queries.count_pending_teams)

    team_info = ""
    if engine.current_team:
        team_info = f"\nCurrent: {engine.current_team['flag']} {engine.current_team['name']}"
        if engine.high_bid:
            team_info += f"  💰 ${engine.high_bid:,} @{engine.high_bidder_username}"

    await update.message.reply_text(
        f"Status: *{engine.status}*{team_info}\n"
        f"Sold: {sold}  |  Remaining: {pending}",
        parse_mode="Markdown",
    )


def register(app: Application, admin_ids: list[int]):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CommandHandler("correct", cmd_correct))
    app.add_handler(CommandHandler("shuffle", cmd_shuffle))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("status", cmd_status))
