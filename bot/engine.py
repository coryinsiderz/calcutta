import asyncio
import logging

from telegram import Bot, InlineKeyboardMarkup

import db.queries as queries
from bot.keyboards import build_bid_keyboard
from bot.timer import SilenceTimer
from db.payouts import build_info_text

logger = logging.getLogger(__name__)


class AuctionEngine:
    def __init__(self):
        self.bot: Bot | None = None
        self.timer = SilenceTimer()
        self.timer.set_callbacks(self._on_going_once, self._on_going_twice, self._on_sold)

        # In-memory state (mirrored to DB after every change)
        self.status = "idle"
        self.current_team: dict | None = None
        self.high_bid: int = 0
        self.high_bidder_user_id: int | None = None
        self.high_bidder_username: str | None = None
        self.bid_message_id: int | None = None
        self.chat_id: int | None = None
        self.silence_phase = "none"

        # Config (reloaded at start of each team)
        self.config: dict = {}
        self.increment_bands: list[dict] = []

        self._advance_task: asyncio.Task | None = None

    # ── Startup ──────────────────────────────────────────────────────────────

    def load_from_db(self):
        state = queries.get_auction_state()
        cfg = queries.get_auction_config()
        bands = queries.get_increment_bands()

        self.config = cfg or {}
        self.increment_bands = bands or []
        self._apply_timer_config()

        if not state:
            return

        self.status = state["status"]
        self.chat_id = state["chat_id"]
        self.high_bid = state["high_bid"] or 0
        self.high_bidder_user_id = state["high_bidder_user_id"]
        self.high_bidder_username = state["high_bidder_username"]
        self.bid_message_id = state["bid_message_id"]
        self.silence_phase = state["silence_phase"] or "none"

        if state["current_team_id"]:
            self.current_team = queries.get_team_by_id(state["current_team_id"])

    def _apply_timer_config(self):
        if self.config:
            self.timer.configure(
                self.config.get("silence_once_sec", 15),
                self.config.get("silence_twice_sec", 5),
                self.config.get("silence_sold_sec", 5),
            )

    async def resume_after_restart(self):
        """Re-announce current team after a worker restart."""
        if self.status != "running" or not self.chat_id or not self.current_team:
            return
        team = self.current_team
        try:
            await self.bot.send_message(
                self.chat_id,
                f"⚙️ Bot restarted — resuming auction.\n\n"
                f"{team['flag']} {team['name'].upper()}\n"
                + (
                    f"💰 Current high: ${self.high_bid:,} — @{self.high_bidder_username}"
                    if self.high_bid
                    else f"Opening bid: /bid <amount> (min ${self.config.get('opening_floor', 1)})"
                ),
            )
            if self.high_bid:
                keyboard = build_bid_keyboard(self.high_bid, team["id"], self.increment_bands)
                msg = await self.bot.send_message(
                    self.chat_id,
                    f"💰 ${self.high_bid:,} — @{self.high_bidder_username}",
                    reply_markup=keyboard,
                )
                self.bid_message_id = msg.message_id
                await asyncio.to_thread(queries.set_bid_message_id, msg.message_id)
                self.timer.reset()
        except Exception:
            logger.exception("Failed to resume auction announcement")

    # ── Public commands ───────────────────────────────────────────────────────

    async def start_auction(self, chat_id: int):
        self.chat_id = chat_id
        # Reload config fresh
        self.config = queries.get_auction_config() or {}
        self.increment_bands = queries.get_increment_bands() or []
        self._apply_timer_config()

        await asyncio.to_thread(queries.set_auction_running, chat_id)
        self.status = "running"
        await self._advance_to_next_team()

    async def pause(self):
        self.timer.cancel()
        self.status = "paused"
        await asyncio.to_thread(queries.set_auction_status, "paused")

    async def resume(self):
        self.status = "running"
        await asyncio.to_thread(queries.set_auction_status, "running")
        if self.high_bid:
            self.timer.reset()

    async def next_team(self):
        """Admin-triggered manual advance."""
        if self._advance_task and not self._advance_task.done():
            self._advance_task.cancel()
        self.timer.cancel()
        await self._advance_to_next_team()

    async def reset(self):
        """Full wipe — all bids/sales cleared, state back to idle, draw reshuffled."""
        self.timer.cancel()
        if self._advance_task and not self._advance_task.done():
            self._advance_task.cancel()

        await asyncio.to_thread(queries.reset_auction)

        self.status = "idle"
        self.current_team = None
        self.high_bid = 0
        self.high_bidder_user_id = None
        self.high_bidder_username = None
        self.bid_message_id = None
        self.silence_phase = "none"

    async def undo_last_sold(self) -> tuple[bool, str]:
        last = await asyncio.to_thread(queries.get_last_sold_team)
        if not last:
            return False, "No teams have been sold yet."

        await asyncio.to_thread(queries.unmark_team_sold, last["id"])

        if self.status == "done":
            self.status = "running"

        # Reset current team to the just-undone team
        self.current_team = last
        self.high_bid = 0
        self.high_bidder_user_id = None
        self.high_bidder_username = None
        self.bid_message_id = None
        self.silence_phase = "none"
        self.timer.cancel()

        await asyncio.to_thread(queries.set_team_active, last["id"])
        await asyncio.to_thread(
            queries.update_auction_state,
            status="running",
            current_team_id=last["id"],
            high_bid=None,
            high_bidder_user_id=None,
            high_bidder_username=None,
            bid_message_id=None,
            silence_phase="none",
        )

        return True, last["name"]

    # ── Bidding ───────────────────────────────────────────────────────────────

    async def process_bid(
        self,
        user_id: int,
        username: str,
        amount: int,
        callback_query=None,
    ) -> tuple[bool, str | None]:

        async def reject(msg: str):
            await asyncio.to_thread(
                queries.reject_bid_log,
                self.current_team["id"] if self.current_team else None,
                user_id,
                username,
                amount,
                msg,
            )
            if callback_query:
                await callback_query.answer(msg, show_alert=True)
            return False, msg

        if self.status == "paused":
            return await reject("Auction is paused.")
        if self.status != "running":
            return await reject("No active auction.")
        if not self.current_team:
            return await reject("No active team.")

        floor = self.config.get("opening_floor", 1)
        if self.high_bid == 0:
            if amount < floor:
                return await reject(f"Minimum opening bid is ${floor}.")
        else:
            from bot.keyboards import _get_increment
            min_next = self.high_bid + _get_increment(self.high_bid, self.increment_bands)
            if amount < min_next:
                return await reject(f"Minimum bid is ${min_next:,}.")

        if user_id == self.high_bidder_user_id:
            return await reject("You already hold the high bid!")

        # Accept
        self.high_bid = amount
        self.high_bidder_user_id = user_id
        self.high_bidder_username = username
        self.silence_phase = "none"

        self.timer.reset()

        await asyncio.to_thread(
            queries.accept_bid_state,
            self.current_team["id"],
            user_id,
            username,
            amount,
        )

        keyboard = build_bid_keyboard(amount, self.current_team["id"], self.increment_bands)
        msg = await self.bot.send_message(
            self.chat_id,
            f"💰 ${amount:,} — @{username}",
            reply_markup=keyboard,
        )
        self.bid_message_id = msg.message_id
        await asyncio.to_thread(queries.set_bid_message_id, msg.message_id)

        if callback_query:
            await callback_query.answer(f"Bid of ${amount:,} accepted!")

        return True, None

    # ── Timer callbacks ───────────────────────────────────────────────────────

    async def _on_going_once(self):
        if self.status != "running" or not self.current_team or not self.high_bid:
            return
        self.silence_phase = "once"
        await asyncio.to_thread(queries.set_silence_phase, "once")

        text = self.config.get("msg_going_once", "Going once... {team} to {bidder} for ${amount}").format(
            team=self.current_team["name"],
            bidder=self.high_bidder_username or "?",
            amount=f"{self.high_bid:,}",
        )
        keyboard = build_bid_keyboard(self.high_bid, self.current_team["id"], self.increment_bands)

        if self.bid_message_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.bid_message_id,
                    text=f"💰 ${self.high_bid:,} — @{self.high_bidder_username}\n\n⚡ {text}",
                    reply_markup=keyboard,
                )
                return
            except Exception:
                pass
        await self.bot.send_message(self.chat_id, f"⚡ {text}")

    async def _on_going_twice(self):
        if self.status != "running" or not self.current_team or not self.high_bid:
            return
        self.silence_phase = "twice"
        await asyncio.to_thread(queries.set_silence_phase, "twice")

        text = self.config.get("msg_going_twice", "Going twice... {team} to {bidder} for ${amount}").format(
            team=self.current_team["name"],
            bidder=self.high_bidder_username or "?",
            amount=f"{self.high_bid:,}",
        )
        keyboard = build_bid_keyboard(self.high_bid, self.current_team["id"], self.increment_bands)

        if self.bid_message_id:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.bid_message_id,
                    text=f"💰 ${self.high_bid:,} — @{self.high_bidder_username}\n\n⚡⚡ {text}",
                    reply_markup=keyboard,
                )
                return
            except Exception:
                pass
        await self.bot.send_message(self.chat_id, f"⚡⚡ {text}")

    async def _on_sold(self):
        if self.status != "running" or not self.current_team or not self.high_bid:
            return

        team = self.current_team
        sold_text = self.config.get("msg_sold", "SOLD! {team} to {bidder} for ${amount} 🔨").format(
            team=team["name"],
            bidder=self.high_bidder_username,
            amount=f"{self.high_bid:,}",
        )

        # Remove keyboard from last bid message
        if self.bid_message_id:
            try:
                await self.bot.edit_message_reply_markup(
                    chat_id=self.chat_id,
                    message_id=self.bid_message_id,
                    reply_markup=None,
                )
            except Exception:
                pass

        await asyncio.to_thread(
            queries.mark_team_sold,
            team["id"],
            self.high_bidder_user_id,
            self.high_bidder_username,
            self.high_bid,
        )

        remaining = await asyncio.to_thread(queries.count_pending_teams)
        await self.bot.send_message(
            self.chat_id,
            f"{team['flag']} {sold_text}\n({remaining} team{'s' if remaining != 1 else ''} remaining)",
        )

        self._advance_task = asyncio.create_task(self._delayed_advance(5))

    async def _delayed_advance(self, seconds: int):
        await asyncio.sleep(seconds)
        await self._advance_to_next_team()

    # ── Internal advance ──────────────────────────────────────────────────────

    async def _advance_to_next_team(self):
        # Reload config for each new team (picks up web panel changes)
        self.config = await asyncio.to_thread(queries.get_auction_config) or {}
        self.increment_bands = await asyncio.to_thread(queries.get_increment_bands) or []
        self._apply_timer_config()

        team = await asyncio.to_thread(queries.get_next_pending_team)

        if not team:
            self.status = "done"
            self.current_team = None
            await asyncio.to_thread(queries.set_auction_status, "done")
            await self.bot.send_message(
                self.chat_id,
                "🏆 All 48 teams sold! Auction complete.\nUse /results for the full breakdown.",
            )
            return

        self.current_team = team
        self.high_bid = 0
        self.high_bidder_user_id = None
        self.high_bidder_username = None
        self.bid_message_id = None
        self.silence_phase = "none"

        await asyncio.to_thread(queries.set_team_active, team["id"])
        await asyncio.to_thread(queries.reset_auction_state_for_team, team["id"])

        sold = await asyncio.to_thread(queries.count_sold_teams)
        total = sold + await asyncio.to_thread(queries.count_pending_teams) + 1

        # Post the running info (pot + per-owner spend) before each reveal
        try:
            info_text = await asyncio.to_thread(build_info_text)
            await self.bot.send_message(self.chat_id, info_text)
        except Exception:
            logger.exception("Failed to post info before team reveal")

        await self.bot.send_message(
            self.chat_id,
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{team['flag']}  {team['name'].upper()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Team {sold + 1} of {total}\n"
            f"Opening bid: /bid <amount>  (min ${self.config.get('opening_floor', 1)})",
        )

    # ── Override handler (from web panel) ─────────────────────────────────────

    async def apply_override(self, override: dict):
        action = override["action"]
        params = override.get("params") or {}

        try:
            if action == "pause":
                if self.status == "running":
                    await self.pause()
                    if self.chat_id:
                        await self.bot.send_message(self.chat_id, "⏸ Auction paused by admin.")

            elif action == "resume":
                if self.status == "paused":
                    await self.resume()
                    if self.chat_id:
                        await self.bot.send_message(self.chat_id, "▶️ Auction resumed by admin.")

            elif action == "undo_last":
                ok, result = await self.undo_last_sold()
                if self.chat_id:
                    if ok:
                        await self.bot.send_message(
                            self.chat_id,
                            f"↩️ Undo! Re-auctioning {result}.\n"
                            f"Opening bid: /bid <amount>  (min ${self.config.get('opening_floor', 1)})",
                        )
                    else:
                        await self.bot.send_message(self.chat_id, f"Undo failed: {result}")

            elif action == "correct_price":
                team_id = params.get("team_id")
                new_price = params.get("new_price")
                if team_id and new_price:
                    await asyncio.to_thread(queries.correct_sold_price, int(team_id), int(new_price))
                    if self.chat_id:
                        team = await asyncio.to_thread(queries.get_team_by_id, int(team_id))
                        name = team["name"] if team else f"team #{team_id}"
                        await self.bot.send_message(
                            self.chat_id,
                            f"✏️ Price corrected: {name} → ${int(new_price):,}",
                        )

            elif action == "set_high_bid":
                if self.current_team and self.status in ("running", "paused"):
                    amount = int(params.get("amount", 0))
                    bidder = params.get("bidder") or "admin"
                    uid = int(params.get("user_id") or 0)
                    self.high_bid = amount
                    self.high_bidder_user_id = uid
                    self.high_bidder_username = bidder
                    self.silence_phase = "none"
                    await asyncio.to_thread(
                        queries.accept_bid_state, self.current_team["id"], uid, bidder, amount
                    )
                    if self.status == "running":
                        self.timer.reset()
                    if self.chat_id:
                        await self.bot.send_message(
                            self.chat_id, f"🛠 Admin set high bid: ${amount:,} — @{bidder}"
                        )

            elif action == "reload_state":
                st = await asyncio.to_thread(queries.get_auction_state)
                if st and st["current_team_id"]:
                    self.current_team = await asyncio.to_thread(
                        queries.get_team_by_id, st["current_team_id"]
                    )

            elif action == "reset":
                await self.reset()
                if self.chat_id:
                    await self.bot.send_message(
                        self.chat_id,
                        "🧹 Auction reset by admin. All teams pending, draw reshuffled. Run /start to begin.",
                    )

            elif action == "reload_config":
                self.config = await asyncio.to_thread(queries.get_auction_config) or {}
                self.increment_bands = await asyncio.to_thread(queries.get_increment_bands) or []
                self._apply_timer_config()
                logger.info("Config reloaded via override")

        except Exception:
            logger.exception("Error applying override %s", action)
