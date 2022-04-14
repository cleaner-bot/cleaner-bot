import asyncio
import typing
import logging

import hikari
import msgpack  # type: ignore

from cleaner_conf.guild import GuildConfig, GuildEntitlements

from ..bot import TheCleaner
from ..shared.event import IGuildSettingsAvailable
from ..shared.sub import listen as pubsub_listen, Message
from ..shared.protect import protect, protected_call


logger = logging.getLogger(__name__)


class GuildData(typing.NamedTuple):
    config: GuildConfig
    entitlements: GuildEntitlements


class ConfigExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    _guilds: dict[int, GuildData]
    _races: dict[int, asyncio.Event]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_new_guild),
            (hikari.GuildAvailableEvent, self.on_new_guild),
            (hikari.GuildLeaveEvent, self.on_destroy_guild),
        ]

        self._guilds = {}
        self._races = {}
        self.task = None

    def on_load(self):
        asyncio.create_task(protected_call(self.loader))
        self.task = asyncio.create_task(protect(self.updated))

    async def loader(self):
        for guild_id in tuple(self.bot.bot.cache.get_guilds_view().keys()):
            if guild_id not in self._guilds:
                await self.fetch_guild(guild_id)

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
            # TODO: investigate usage of .construct() instead
            self._guilds[guild_id] = GuildData(
                GuildConfig.construct(**guild_config),
                GuildEntitlements.construct(**guild_entitlements),
            )
        except Exception as e:
            logger.error(
                f"error during fetching settings for guild: {guild_id}", exc_info=e
            )
        else:
            logger.debug(f"fetched settings for {guild_id}")
        finally:
            event.set()

        guild = self.bot.extensions.get("clend.guild", None)
        if guild is None:
            return logger.warning("unable to find clend.guild extension")
        guild.send_event(IGuildSettingsAvailable(guild_id))

    async def fetch_dict(self, key: str, keys: typing.Sequence[str]):
        database = self.bot.database
        values = await database.hmget(key, keys)
        return {k: msgpack.unpackb(v) for k, v in zip(keys, values) if v is not None}

    def get_config(self, guild_id: int) -> GuildConfig | None:
        gd = self._guilds.get(guild_id, None)
        if gd is not None:
            return gd.config
        return None

    def get_entitlements(self, guild_id: int) -> GuildEntitlements | None:
        gd = self._guilds.get(guild_id, None)
        if gd is not None:
            return gd.entitlements
        return None

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
        pubsub = self.bot.database.pubsub()
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
                    logger.debug(
                        f"changed {space}.{name} to {value!r} ({data['guild_id']})"
                    )
                    setattr(obj, name, value)
