from __future__ import annotations

import logging
import threading
import typing
import queue

import hikari

from .guild import CleanerGuild
from ..bot import TheCleaner
from ..shared.event import IGuildSettingsAvailable, IAction


WORKERS = 4
ComponentListener = typing.Callable[
    [hikari.Event, CleanerGuild], list[IAction | None] | None
]
logger = logging.getLogger(__name__)


class GuildExtension:
    guilds: dict[int, CleanerGuild]
    callbacks: dict[typing.Type[hikari.Event], list[ComponentListener]]
    workers: list[GuildWorker] | None = None
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner) -> None:
        self.bot = bot
        self.guilds = {}
        self.listeners = []

        from .components import components

        self.callbacks = {}
        for component in components:
            for type, func in component.listeners:
                if type not in self.callbacks:
                    self.callbacks[type] = []
                    self.listeners.append((type, self.dispatch))
                self.callbacks[type].append(func)

    def on_load(self):
        self.workers = [GuildWorker(self, idx, WORKERS) for idx in range(WORKERS)]
        for worker in self.workers:
            worker.start()

    def on_unload(self):
        if self.workers:
            for worker in self.workers:
                worker.queue.put(None)

    def send_event(self, event: hikari.Event):
        if self.workers is None:
            return False

        guild_id = getattr(event, "guild_id", None)

        if guild_id is None:
            for worker in self.workers:
                worker.queue.put(event)

        else:
            worker = self.workers[guild_id % WORKERS]
            worker.queue.put(event)

        return True

    async def dispatch(self, event: hikari.Event):
        self.send_event(event)


class GuildWorker(threading.Thread):
    queue: queue.Queue[hikari.Event]

    def __init__(
        self, ext: GuildExtension, worker_index: int, worker_count: int
    ) -> None:
        super().__init__()
        self.ext = ext
        self.queue = queue.Queue()
        self.worker_index = worker_index
        self.worker_count = worker_count

    def run(self) -> None:
        while True:
            event: hikari.Event = self.queue.get()
            if event is None:
                break

            guild_id = getattr(event, "guild_id", None)
            if guild_id is None:  # global event
                # make a copy because it might not be threadsafe
                guild_ids = tuple(self.ext.guilds.keys())
                for guild_id in guild_ids:
                    # responsible for this guild
                    if guild_id % self.worker_count == self.worker_index:
                        self.send_event(event, guild_id)
            else:  # guild event
                self.send_event(event, guild_id)

    def send_event(self, event: hikari.Event, guild_id: int):
        guild = self.ext.guilds.get(guild_id, None)
        if guild is None:
            self.ext.guilds[guild_id] = guild = CleanerGuild(guild_id, self.ext.bot)
            if guild.get_config() is not None:
                guild.settings_loaded = True

        if isinstance(event, IGuildSettingsAvailable):
            while not guild.event_queue.empty():
                event = guild.event_queue.get_nowait()
                self.event(event, guild)
            guild.settings_loaded = True
        elif not guild.settings_loaded:
            guild.event_queue.put(event)
        else:
            self.event(event, guild)

    def event(self, event: hikari.Event, guild: CleanerGuild):
        callbacks = self.ext.callbacks.get(type(event), None)
        if callbacks is None:
            return
        data = None
        for func in callbacks:
            data = func(event, guild)
            if data is not None:
                break
        else:
            return

        http = self.ext.bot.extensions.get("clend.http", None)
        if http is None:
            logger.warning("action required but http extension is not loaded")
        else:
            for item in data:
                if item is not None:
                    http.queue.sync_q.put(item)
