import importlib
import logging
import typing

from coredis import StrictRedis
import hikari
from hikari.api.config import CacheComponents
from hikari.impl.config import CacheSettings


DEVELOPERS = {
    633993042755452932,
}


class TheCleaner:
    extensions: dict[str, typing.Any]
    guild_has_members_cached: set[int]

    def __init__(self, token: str) -> None:
        intents = hikari.Intents.ALL_GUILDS_UNPRIVILEGED | hikari.Intents.GUILD_MEMBERS

        cache_settings = CacheSettings()
        cache_settings.components = (
            CacheComponents.GUILDS
            | CacheComponents.GUILD_CHANNELS
            | CacheComponents.ROLES
            | CacheComponents.MEMBERS
            | CacheComponents.ME
        )

        # TODO: hikari@2.0.0dev109 add auto_chunk_members=False
        self.bot = hikari.GatewayBot(
            token=token, intents=intents, cache_settings=cache_settings
        )
        logging.getLogger("clend").setLevel(logging.DEBUG)
        # spammy with pretty much useless info
        logging.getLogger("clend.conf").setLevel(logging.INFO)
        self.database = StrictRedis()

        self.extensions = {}
        self.guild_has_members_cached = set()

    def run(self, **kwargs):
        self.bot.run(**kwargs)

    def load_extension(self, module: str):
        if module in self.extensions:
            raise RuntimeError(f"extension already loaded: {module!r}")
        mod = importlib.import_module(module)
        self.extensions[module] = ext = mod.extension(self)
        for event, callback in ext.listeners:
            self.bot.subscribe(event, callback)
        if hasattr(ext, "on_load"):
            ext.on_load()

    def unload_extension(self, module: str):
        ext = self.extensions[module]
        if hasattr(ext, "on_unload"):
            ext.on_unload()
        for event, callback in ext.listeners:
            self.bot.unsubscribe(event, callback)
        del self.extensions[module]

    @staticmethod
    def is_developer(user_id: int) -> bool:
        return user_id in DEVELOPERS
