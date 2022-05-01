import asyncio
import typing
import os

import hikari

from downdoom import Client

from ..app import TheCleanerApp


class DowndoomExtension:
    task: asyncio.Task | None = None
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
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
