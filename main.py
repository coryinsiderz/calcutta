import asyncio
import logging
import os
import threading

from dotenv import load_dotenv

load_dotenv()

from telegram.ext import Application

import db.queries as queries
from bot.engine import AuctionEngine
from bot.handlers import admin, auction, general
from db import schema
from web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def _override_poller(engine: AuctionEngine):
    """Poll pending_overrides every 2 s and apply them."""
    while True:
        try:
            overrides = await asyncio.to_thread(queries.get_pending_overrides)
            for o in overrides:
                await engine.apply_override(o)
                await asyncio.to_thread(queries.mark_override_applied, o["id"])
        except Exception:
            logger.exception("Override poller error")
        await asyncio.sleep(2)


def _run_web():
    """Serve the Flask web panel in a background thread (waitress, production WSGI)."""
    from waitress import serve

    logging.getLogger("waitress").setLevel(logging.WARNING)
    port = int(os.environ.get("PORT", 8080))
    web_app = create_app()
    logger.info("Starting web panel on 0.0.0.0:%s", port)
    serve(web_app, host="0.0.0.0", port=port, threads=8)


def main():
    schema.apply_schema()
    schema.seed_defaults()

    # Web panel runs in a daemon thread; the bot owns the main thread (signals).
    threading.Thread(target=_run_web, daemon=True, name="web").start()

    engine = AuctionEngine()
    engine.load_from_db()

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    raw_ids = os.environ.get("ADMIN_USER_IDS", "")
    admin_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]

    logger.info("Admin user IDs: %s", admin_ids)
    logger.info("Auction status on startup: %s", engine.status)

    async def post_init(application: Application):
        engine.bot = application.bot
        application.bot_data["engine"] = engine
        application.bot_data["admin_ids"] = admin_ids

        if engine.status == "running" and engine.chat_id:
            logger.info("Resuming live auction in chat %s", engine.chat_id)
            await engine.resume_after_restart()

        asyncio.create_task(_override_poller(engine))
        logger.info("Bot ready — override poller started")

    application = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    general.register(application)
    admin.register(application, admin_ids)
    auction.register(application)

    logger.info("Starting long-poll worker")
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
