import asyncio
import threading
import typing

import hikari
import janus

from ..app import TheCleanerApp
from ..shared.event import IGuildEvent
from ..shared.protect import protect
from .http import HTTPService


class HTTPExtension(threading.Thread):
    queue: janus.Queue[IGuildEvent]
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]
    tasks: list[asyncio.Task[None]] | None = None

    def __init__(self, app: TheCleanerApp) -> None:
        super().__init__()
        self.app = app
        self.listeners = []
        self.http = HTTPService(app)
        self.queue = self.http.main_queue

    def on_load(self) -> None:
        self.tasks = [
            asyncio.create_task(protect(self.http.ind)),
            asyncio.create_task(protect(self.http.logd)),
            asyncio.create_task(protect(self.http.deleted)),
        ]

    def on_unload(self) -> None:
        if self.tasks is not None:
            for task in self.tasks:
                task.cancel()
