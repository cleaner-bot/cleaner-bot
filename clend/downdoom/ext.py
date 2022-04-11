import asyncio
import typing
import os

import hikari

from downdoom import Client

from ..bot import TheCleaner


class DowndoomExtension:
    task: asyncio.Task | None = None
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner) -> None:
        self.bot = bot
        self.listeners = []

        host = os.getenv("DOWNDOOM_HOST")
        if host is None:
            self.client = None
        else:
            self.client = Client("cleaner-bot", host)

    def on_load(self):
        if self.client is not None:
            self.task = asyncio.create_task(self.client.run())

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()
