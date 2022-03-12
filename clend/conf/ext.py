import asyncio
import typing
import json
import logging

import hikari

from cleaner_conf import Config, config, Entitlements, entitlements

from ..bot import TheCleaner
from ..shared.event import IGuildSettingsAvailable
from ..shared.sub import listen as pubsub_listen, Message


logger = logging.getLogger(__name__)


class GuildData(typing.NamedTuple):
    config: Config
    entitlements: Entitlements


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
        for guild_id in self.bot.bot.cache.get_guilds_view().keys():
            if guild_id not in self._guilds:
                logger.debug(f"scheduled config:fetch_guild({guild_id})")
                asyncio.create_task(self.fetch_guild(guild_id))

        self.task = asyncio.create_task(self.updated())

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
            database = self.bot.database
            guild_entitlements = Entitlements()
            guild_config = Config()

            for key, value in entitlements.items():
                db = await database.get(f"guild:{guild_id}:entitlement:{key}")
                if db is None:
                    db = value.default
                else:
                    db = value.from_string(db.decode())

                setattr(guild_entitlements, key, db)

            for key, value in config.items():
                db = await database.get(f"guild:{guild_id}:config:{key}")
                if db is None:
                    db = value.default
                else:
                    db = value.from_string(db.decode())

                setattr(guild_config, key, db)

            self._guilds[guild_id] = GuildData(guild_config, guild_entitlements)
        except Exception as e:
            logger.error(f"error during config:fetch_guild({guild_id})", exc_info=e)
        else:
            logger.debug(f"done config:fetch_guild({guild_id})")
        finally:
            event.set()

        guild = self.bot.extensions.get("clend.guild", None)
        if guild is None:
            return logger.warning("unable to find clend.guild extension")
        guild.send_event(IGuildSettingsAvailable(guild_id))

    def get_config(self, guild_id: int) -> typing.Optional[Config]:
        gd = self._guilds.get(guild_id, None)
        if gd is not None:
            return gd.config
        return None

    def get_entitlements(self, guild_id: int) -> typing.Optional[Entitlements]:
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
        while True:
            try:
                await self._updated()
            except Exception as e:
                logger.exception("Exception occured during updated", exc_info=e)

    async def _updated(self):
        pubsub = self.bot.database.pubsub()
        await pubsub.subscribe("pubsub:config-update")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, Message):
                continue

            data = json.loads(event.data)
            gd = self._guilds.get(data["guild_id"], None)
            if gd is None:
                continue

            obj = gd.config if data["table"] == "config" else gd.entitlements
            validators = config if data["table"] == "config" else entitlements

            for name, value in data["changes"].items():
                logger.debug(
                    f"changed {data['table']}.{name} to {value!r} ({data['guild_id']})"
                )
                setattr(obj, name, validators[name].from_string(value))
