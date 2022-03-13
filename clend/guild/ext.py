from __future__ import annotations

import logging
import threading
import typing
import queue

import hikari

from .guild import CleanerGuild
from ..bot import TheCleaner
from ..shared.event import IGuildEvent, IGuildSettingsAvailable, IAction


WORKERS = 4
ComponentListener = typing.Callable[[IGuildEvent, CleanerGuild], None | list[IAction]]
logger = logging.getLogger(__name__)


class GuildExtension:
    guilds: dict[int, CleanerGuild]
    callbacks: dict[typing.Type[IGuildEvent], list[ComponentListener]]
    workers: typing.Optional[list[GuildWorker]] = None
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
        self.workers = [GuildWorker(self) for _ in range(WORKERS)]
        for worker in self.workers:
            worker.start()

    def on_unload(self):
        if self.workers:
            for worker in self.workers:
                worker.queue.put(None)

    def send_event(self, data: IGuildEvent):
        if self.workers is None:
            return False
        worker = self.workers[data.guild_id % WORKERS]
        worker.queue.put(data)
        return True

    async def dispatch(self, event: IGuildEvent):
        self.send_event(event)


class GuildWorker(threading.Thread):
    queue: queue.Queue[IGuildEvent]

    def __init__(self, ext: GuildExtension) -> None:
        super().__init__()
        self.ext = ext
        self.queue = queue.Queue()

    def run(self) -> None:
        while True:
            event: IGuildEvent = self.queue.get()
            if event is None:
                break

            guild = self.ext.guilds.get(event.guild_id, None)
            if guild is None:
                guild_id = event.guild_id
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

    def event(self, event: IGuildEvent, guild: CleanerGuild):
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
                http.queue.sync_q.put(item)
