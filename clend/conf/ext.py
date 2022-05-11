import asyncio
import logging
import typing

import hikari
import msgpack  # type: ignore
from cleaner_conf.guild import GuildConfig, GuildEntitlements

from ..app import TheCleanerApp
from ..shared.data import GuildData, GuildWorker
from ..shared.event import IGuildSettingsAvailable
from ..shared.protect import protect, protected_call
from ..shared.sub import Message
from ..shared.sub import listen as pubsub_listen

logger = logging.getLogger(__name__)


class ConfigExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    _guilds: dict[int, GuildData]
    _races: dict[int, asyncio.Event]

    def __init__(self, app: TheCleanerApp):
        self.app = app
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_new_guild),
            (hikari.GuildAvailableEvent, self.on_new_guild),
            (hikari.GuildLeaveEvent, self.on_destroy_guild),
        ]

        self._guilds = {}
        self._races = {}
        self.task = None

    def on_load(self):
        asyncio.create_task(protected_call(self.loader()))
        self.task = asyncio.create_task(protect(self.updated))

    async def loader(self):
        for guild_id in tuple(self.app.bot.cache.get_guilds_view().keys()):
            if guild_id not in self._guilds:
                await self.fetch_guild(guild_id)
        logger.info("initial setting fetch done")

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def fetch_guild(self, guild_id: int):
        event = self._races.get(guild_id, None)
        if event is not None:
            await event.wait()
            return

        self._races[guild_id] = event = asyncio.Event()
        try:
            guild_config = await self.fetch_dict(
                f"guild:{guild_id}:config", tuple(GuildConfig.__fields__)
            )
            guild_entitlements = await self.fetch_dict(
                f"guild:{guild_id}:entitlements",
                tuple(GuildEntitlements.__fields__),
            )
            guild_worker = await self.app.database.get(f"guild:{guild_id}:worker")
            self._guilds[guild_id] = GuildData(
                GuildConfig.construct(**guild_config),
                GuildEntitlements.construct(**guild_entitlements),
                GuildWorker(guild_worker.decode() if guild_worker else ""),
            )
        except Exception as e:
            logger.error(
                f"error during fetching settings for guild: {guild_id}", exc_info=e
            )
        else:
            logger.debug(f"fetched settings for {guild_id}")
        finally:
            event.set()
            del self._races[guild_id]

        guild = self.app.extensions.get("clend.guild", None)
        if guild is None:
            return logger.warning("unable to find clend.guild extension")
        guild.send_event(IGuildSettingsAvailable(guild_id))

    async def fetch_dict(self, key: str, keys: tuple[str, ...]):
        database = self.app.database
        values = await database.hmget(key, keys)
        return {k: msgpack.unpackb(v) for k, v in zip(keys, values) if v is not None}

    def get_data(self, guild_id: int) -> GuildData | None:
        return self._guilds.get(guild_id, None)

    async def ensure_guild(self, guild_id: int):
        if guild_id not in self._guilds:
            await self.fetch_guild(guild_id)

    async def on_new_guild(
        self, event: hikari.GuildJoinEvent | hikari.GuildAvailableEvent
    ):
        if event.guild_id not in self._guilds:
            await self.fetch_guild(event.guild_id)

    async def on_destroy_guild(self, event: hikari.GuildLeaveEvent):
        if event.guild_id in self._guilds:
            del self._guilds[event.guild_id]

    async def updated(self):
        pubsub = self.app.database.pubsub()
        await pubsub.subscribe("pubsub:settings-update")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, Message):
                continue

            data = msgpack.unpackb(event.data)
            gd = self._guilds.get(data["guild_id"], None)
            if gd is None:
                continue

            for space in ("config", "entitlements"):
                if space not in data:
                    continue
                obj = getattr(gd, space)
                for name, value in data[space].items():
                    logger.info(
                        f"changed {space}.{name} to {value!r} ({data['guild_id']})"
                    )
                    setattr(obj, name, value)

            if "worker" in data:
                logger.info(f"changed worker in {data['guild_id']}")
                gd.worker.source = data["worker"]
