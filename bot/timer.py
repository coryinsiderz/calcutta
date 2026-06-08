import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class SilenceTimer:
    """Inactivity timer that fires going-once → going-twice → sold callbacks."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._once_sec = 15
        self._twice_sec = 5
        self._sold_sec = 5
        self._on_once: Callable[[], Awaitable] | None = None
        self._on_twice: Callable[[], Awaitable] | None = None
        self._on_sold: Callable[[], Awaitable] | None = None

    def configure(self, once_sec: int, twice_sec: int, sold_sec: int):
        self._once_sec = once_sec
        self._twice_sec = twice_sec
        self._sold_sec = sold_sec

    def set_callbacks(
        self,
        on_once: Callable[[], Awaitable],
        on_twice: Callable[[], Awaitable],
        on_sold: Callable[[], Awaitable],
    ):
        self._on_once = on_once
        self._on_twice = on_twice
        self._on_sold = on_sold

    def reset(self):
        self.cancel()
        self._task = asyncio.create_task(self._run())

    def cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _run(self):
        try:
            await asyncio.sleep(self._once_sec)
            if self._on_once:
                await self._on_once()
            await asyncio.sleep(self._twice_sec)
            if self._on_twice:
                await self._on_twice()
            await asyncio.sleep(self._sold_sec)
            if self._on_sold:
                await self._on_sold()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error in silence timer")
