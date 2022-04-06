import asyncio
import logging
import typing

import hikari

from ..bot import TheCleaner
from ..shared.protect import protect
from ..shared.custom_events import FastTimerEvent, SlowTimerEvent


logger = logging.getLogger(__name__)


class TimerExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = []
        self.task = None

    def on_load(self):
        self.task = asyncio.create_task(protect(self.timerd))

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def timerd(self):
        sequence = 0
        while True:
            fast_timer_event = FastTimerEvent(self.bot.bot, sequence=sequence)
            self.bot.bot.dispatch(fast_timer_event)
            if sequence % 30 == 0:
                slow_timer_event = SlowTimerEvent(self.bot.bot, sequence=sequence // 30)
                self.bot.bot.dispatch(slow_timer_event)

            sequence += 1

            await asyncio.sleep(10)
