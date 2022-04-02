import asyncio
import logging
import typing

import hikari

from ..bot import TheCleaner
from ..shared.protect import protect
from ..shared.custom_events import TimerEvent


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
            event = TimerEvent(self.bot.bot, sequence=sequence)
            self.bot.bot.dispatch(event)
            sequence += 1

            await asyncio.sleep(30)
