import importlib
import logging
import typing

import coredis  # type: ignore
import hikari


DEVELOPERS = {
    633993042755452932,
}


class TheCleaner:
    extensions: dict[str, typing.Any]
    guild_has_members_cached: set[int]

    def __init__(self, token: str) -> None:
        intents = hikari.Intents.ALL_GUILDS_UNPRIVILEGED | hikari.Intents.GUILD_MEMBERS

        cache_settings = hikari.CacheSettings()
        cache_settings.components = (
            hikari.CacheComponents.GUILDS
            | hikari.CacheComponents.GUILD_CHANNELS
            | hikari.CacheComponents.ROLES
            | hikari.CacheComponents.MEMBERS
        )

        self.bot = hikari.GatewayBot(
            token=token, intents=intents, cache_settings=cache_settings
        )
        logging.getLogger("clend").setLevel(logging.DEBUG)
        self.database = coredis.StrictRedis()

        self.extensions = {}
        self.guild_has_members_cached = set()

    def run(self):
        self.bot.run()

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
