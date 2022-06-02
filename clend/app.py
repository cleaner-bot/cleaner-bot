from __future__ import annotations

import importlib
import logging
import os
import typing

import hikari
from coredis import Redis
from hikari.api.config import CacheComponents
from hikari.impl.config import CacheSettings

DEVELOPERS = {
    633993042755452932,
}

if typing.TYPE_CHECKING:
    from .store import Store


class TheCleanerApp:
    extensions: dict[str, typing.Any]
    guild_has_members_cached: set[int]
    store: Store

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

        self.bot = hikari.GatewayBot(
            token=token,
            intents=intents,
            cache_settings=cache_settings,
            auto_chunk_members=False,
        )
        logging.getLogger("clend").setLevel(logging.DEBUG)
        # spammy with pretty much useless info
        logging.getLogger("clend.conf").setLevel(logging.INFO)

        redis_host = os.getenv("redis/host", "localhost")
        redis_passwd = os.getenv("redis/password")
        if redis_passwd is None:
            raise RuntimeError("missing redis/password secret")
        self.database = Redis.from_url(f"redis://:{redis_passwd}@{redis_host}:6379")

        self.extensions = {}
        self.guild_has_members_cached = set()

    def load_store(self) -> None:
        from .store import Store

        self.store = Store(self)

    def load_extension(self, module: str) -> None:
        if module in self.extensions:
            raise RuntimeError(f"extension already loaded: {module!r}")
        mod = importlib.import_module(module)
        self.extensions[module] = ext = mod.extension(self)
        for event, callback in ext.listeners:
            self.bot.subscribe(event, callback)
        if hasattr(ext, "on_load"):
            ext.on_load()

    def unload_extension(self, module: str) -> None:
        ext = self.extensions[module]
        if hasattr(ext, "on_unload"):
            ext.on_unload()
        for event, callback in ext.listeners:
            self.bot.unsubscribe(event, callback)
        del self.extensions[module]

    @staticmethod
    def is_developer(user_id: int) -> bool:
        return user_id in DEVELOPERS
