from __future__ import annotations

import asyncio
import logging
import threading
import typing
import queue

from cleaner_conf import entitlements, config
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
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_new_guild),
            (hikari.GuildAvailableEvent, self.on_new_guild),

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
        # ensure guilds are cached after reload
        for guild_id in self.bot.bot.cache.get_guilds_view().keys():
            asyncio.ensure_future(self.get_guild(guild_id))

    def on_unload(self):
        if self.workers:
            for worker in self.workers:
                worker.queue.put(None)

    def send_event(self, data: IGuildEvent):
        if data.guild_id not in self.guilds or self.workers is None:
            return False
        worker = self.workers[data.guild_id % WORKERS]
        worker.queue.put(data)
        return True

    async def dispatch(self, event: IGuildEvent):
        if event.guild_id not in self.guilds:
            await self.get_guild(event.guild_id)
        self.send_event(event)

    async def on_new_guild(
        self, event: hikari.GuildJoinEvent | hikari.GuildAvailableEvent
    ):
        await self.get_guild(event.guild_id)  # ensure the guild is cached

    async def get_guild(self, guild_id: int):
        guild = self.guilds.get(guild_id, None)
        if guild is not None:
            return guild
        logger.info(f"caching guild: {guild_id}")
        self.guilds[guild_id] = guild = CleanerGuild(guild_id)

        database = self.bot.database
        for key, value in entitlements.items():
            db = await database.get(f"guild:{guild_id}:entitlement:{key}")
            if db is None:
                db = value.default
            else:
                db = value.from_string(db.decode())

            setattr(guild.entitlements, key, db)

        for key, value in config.items():
            db = await database.get(f"guild:{guild_id}:config:{key}")
            if db is None:
                db = value.default
            else:
                db = value.from_string(db.decode())

            setattr(guild.config, key, db)

        guild.settings_loaded = True
        self.send_event(IGuildSettingsAvailable(guild_id))


class GuildWorker(threading.Thread):
    queue: queue.Queue[IGuildEvent]

    def __init__(self, ext: GuildExtension) -> None:
        super().__init__()
        self.ext = ext
        self.queue = queue.Queue()

    def run(self) -> None:
        while True:
            event: IGuildEvent = self.queue.get()
            print(event)
            if event is None:
                break

            guild = self.ext.guilds.get(event.guild_id)
            if guild is None:
                logger.warn(f"received event for non-cached guild {event.guild_id}")
                continue

            if isinstance(event, IGuildSettingsAvailable):
                while not guild.event_queue.empty():
                    event = guild.event_queue.get_nowait()
                    self.event(event, guild)
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
            logger.warn("action required but http extension is not loaded")
        else:
            for item in data:
                http.queue.put(item)
