import asyncio
import os
import typing

import hikari
from downdoom import Client

from ..app import TheCleanerApp


class DowndoomExtension:
    task: asyncio.Task[None] | None = None
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = []

        host = os.getenv("downdoom/host")
        if host is None:
            self.client = None
        else:
            self.client = Client("cleaner-bot", host)

    def on_load(self) -> None:
        if self.client is not None:
            self.task = asyncio.create_task(self.client.run())

    def on_unload(self) -> None:
        if self.task is not None:
            self.task.cancel()
