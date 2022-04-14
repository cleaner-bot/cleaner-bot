import asyncio
import threading
import typing

import hikari
import janus

from .http import HTTPService
from ..bot import TheCleaner
from ..shared.event import IGuildEvent
from ..shared.protect import protect


class HTTPExtension(threading.Thread):
    queue: janus.Queue[IGuildEvent]
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner) -> None:
        super().__init__()
        self.bot = bot
        self.listeners = []
        self.http = HTTPService(self.bot)
        self.queue = self.http.main_queue
        self.tasks = None

    def on_load(self):
        self.tasks = [
            asyncio.create_task(protect(self.http.ind)),
            asyncio.create_task(protect(self.http.logd)),
        ]

    def on_unload(self):
        if self.tasks is not None:
            for task in self.tasks:
                task.cancel()

        self.http.metrics.flush()
        self.http.metrics.close()
