import asyncio
import logging
import typing

import hikari

from ..app import TheCleanerApp
from ..shared.custom_events import FastTimerEvent, SlowTimerEvent
from ..shared.protect import protect

logger = logging.getLogger(__name__)


class TimerExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]
    task: asyncio.Task[None] | None = None

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = []

    def on_load(self) -> None:
        self.task = asyncio.create_task(protect(self.timerd))

    def on_unload(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def timerd(self) -> None:
        sequence = 0
        while True:
            fast_timer_event = FastTimerEvent(self.app.bot, sequence=sequence)
            self.app.bot.dispatch(fast_timer_event)
            if sequence % 30 == 0:
                slow_timer_event = SlowTimerEvent(self.app.bot, sequence=sequence // 30)
                self.app.bot.dispatch(slow_timer_event)

            sequence += 1

            await asyncio.sleep(10)
