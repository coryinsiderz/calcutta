import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import db.queries as queries
from db.payouts import build_info_text

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
    await update.message.reply_text("Auction paused.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    engine = context.bot_data["engine"]
    if engine.status != "paused":
        await update.message.reply_text(f"Can't resume — status is '{engine.status}'.")
        return
    await engine.resume()
    await update.message.reply_text("Auction resumed.")


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
            f"Undo! Re-auctioning {result}.\n"
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
        f"Corrected: {last['flag']} {last['name']} → ${amount:,}  (was ${last['sold_price']:,})"
    )


# ── /reset ────────────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /reset CONFIRM  — wipes all bids/sales, resets to idle, reshuffles."""
    if not await _require_admin(update, context):
        return

    args = context.args
    if not args or args[0].strip().lower() != "confirm":
        await update.message.reply_text(
            "This wipes ALL bids and sold teams and resets the auction to idle.\n"
            "Nothing is recoverable. To confirm, send:\n\n/reset confirm"
        )
        return

    engine = context.bot_data["engine"]
    ok = await engine.reset()
    if ok:
        await update.message.reply_text(
            "Auction reset. All 48 teams pending, draw reshuffled, status idle.\nRun /start to begin."
        )
    else:
        await update.message.reply_text(
            "Reset refused — auction is FROZEN. Run /unfreeze first if you really mean it."
        )


async def cmd_freeze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    await asyncio.to_thread(queries.set_frozen, True)
    await asyncio.to_thread(queries.save_snapshot, "auto-freeze")
    await update.message.reply_text(
        "Auction FROZEN. Results are locked and /reset is blocked. A snapshot was saved.\n"
        "Tournament progress can still be updated. Use /unfreeze to unlock."
    )


async def cmd_unfreeze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_admin(update, context):
        return
    await asyncio.to_thread(queries.set_frozen, False)
    await update.message.reply_text("Auction unfrozen. /reset is enabled again.")


# ── /sold (manual logging for a human-run auction) ────────────────────────────

async def cmd_sold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log a sale when a human is auctioneering.
    Usage: /sold <team>, <owner>, <price>   e.g. /sold Brazil, dave, 120"""
    if not await _require_admin(update, context):
        return

    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        await update.message.reply_text(
            "Usage: /sold <team>, <owner>, <price>\ne.g. /sold Brazil, dave, 120"
        )
        return

    team_q, owner, price_s = parts
    owner = owner.lstrip("@")
    price_clean = price_s.lstrip("$").replace(",", "")
    if not price_clean.isdigit():
        await update.message.reply_text("Price must be a number, e.g. /sold Brazil, dave, 120")
        return
    price = int(price_clean)

    teams = await asyncio.to_thread(queries.get_all_teams)
    ql = team_q.lower()
    exact = [t for t in teams if t["name"].lower() == ql]
    matches = exact or [t for t in teams if ql in t["name"].lower()]

    if not matches:
        await update.message.reply_text(f"No team matches '{team_q}'.")
        return
    if len(matches) > 1:
        names = ", ".join(t["name"] for t in matches[:8])
        await update.message.reply_text(f"'{team_q}' matches multiple: {names}. Be more specific.")
        return

    team = matches[0]
    already = team["status"] == "sold"
    await asyncio.to_thread(queries.mark_team_sold, team["id"], 0, owner, price)

    info = await asyncio.to_thread(build_info_text)
    verb = "Updated" if already else "Sold"
    await update.message.reply_text(
        f"{verb}: {team['flag']} {team['name']} -> @{owner} for ${price:,}\n\n{info}"
    )


async def cmd_remaining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List teams not yet sold."""
    teams = await asyncio.to_thread(queries.get_all_teams)
    pending = [t for t in teams if t["status"] != "sold"]
    if not pending:
        await update.message.reply_text("All 48 teams are sold.")
        return
    lines = [f"{len(pending)} teams left:"]
    lines += [f"{t['flag']} {t['name']}" for t in pending]
    await update.message.reply_text("\n".join(lines))


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

    frozen = await asyncio.to_thread(queries.get_frozen)

    team_info = ""
    if engine.current_team:
        team_info = f"\nCurrent: {engine.current_team['flag']} {engine.current_team['name']}"
        if engine.high_bid:
            team_info += f"  ${engine.high_bid:,} @{engine.high_bidder_username}"

    frozen_line = "\nFROZEN (reset locked)" if frozen else ""

    await update.message.reply_text(
        f"Status: *{engine.status}*{frozen_line}{team_info}\n"
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
    app.add_handler(CommandHandler("sold", cmd_sold))
    app.add_handler(CommandHandler("remaining", cmd_remaining))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("freeze", cmd_freeze))
    app.add_handler(CommandHandler("unfreeze", cmd_unfreeze))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("status", cmd_status))
