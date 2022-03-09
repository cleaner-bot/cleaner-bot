import threading
import queue
import typing

import hikari

from .http import HTTPService
from ..bot import TheCleaner


class HTTPExtension(threading.Thread):
    queue: queue.Queue
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    dependencies: list[str]

    def __init__(self, bot: TheCleaner) -> None:
        super().__init__()
        self.bot = bot
        self.queue = queue.Queue()
        self.listeners = []
        self.dependencies = []
        self.http = HTTPService()

    def on_load(self):
        self.start()

    def on_unload(self):
        self.queue.put(None)

    def run(self):
        while True:
            event = self.queue.get()
            if event is None:
                break
            print("http", event)
