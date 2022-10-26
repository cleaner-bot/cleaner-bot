"""
Hypervisor of The Cleaner.

Creates the GatewayBot and Redis database connection.
Has utilities for loading the kernel and recovery mode.
"""

import importlib
import logging
import os
import sys
import typing

import hikari
from coredis import Redis
from hikari.api.config import CacheComponents
from hikari.impl.config import CacheSettings

logger = logging.getLogger(__name__)


class CleanerHypervisor:
    _kernel_name = "cleaner.kernel.kernel:CleanerKernel"
    _kernel: typing.Any = None
    _recovery_name = "cleaner.kernel.recovery:CleanerRecovery"
    _recovery: typing.Any = None

    bot: hikari.GatewayBot
    database: Redis[bytes]

    def __init__(self, token: str) -> None:
        self.bot = create_gateway_bot(token)
        self.database = create_redis()

        setup_logs()

    def load_kernel(self) -> bool:
        try:
            self._kernel = self._try_load(self._kernel_name)
        except Exception as e:
            logger.exception("Exception occured loading kernel", exc_info=e)
            return False
        return True

    def unload_kernel(self) -> None:
        self._kernel = None

    def load_recovery(self) -> bool:
        try:
            self._recovery = self._try_load(self._recovery_name)
        except Exception as e:
            logger.exception("Exception occured loading recovery", exc_info=e)
            return False
        return True

    def unload_recovery(self) -> None:
        self._recovery = None

    def is_kernel_loaded(self) -> bool:
        return self._kernel is not None

    def is_recovery_loaded(self) -> bool:
        return self._recovery is not None

    def _try_load(self, name: str) -> typing.Any:
        logger.info(f"loading: {name}")
        module_name, class_name = name.split(":")
        if module_name in sys.modules:
            sys.modules.pop(module_name)
        module = importlib.import_module(module_name)
        sys.modules.pop(module_name)
        raw_class = getattr(module, class_name)
        return raw_class(self)

    def reload(self) -> None:
        if self.is_kernel_loaded():
            self.unload_kernel()
        if self.is_recovery_loaded():
            self.unload_recovery()

        logger.info("loading kernel")
        if not self.load_kernel():
            logger.info("failed kernel; loading recovery")
            self.load_recovery()
        logger.info("loading done")


def create_gateway_bot(token: str) -> hikari.GatewayBot:
    intents = hikari.Intents.ALL_GUILDS_UNPRIVILEGED | hikari.Intents.GUILD_MEMBERS

    cache_settings = CacheSettings()
    cache_settings.components = (
        CacheComponents.GUILDS
        | CacheComponents.GUILD_CHANNELS
        | CacheComponents.ROLES
        | CacheComponents.MEMBERS
        | CacheComponents.ME
    )

    return hikari.GatewayBot(
        token=token,
        intents=intents,
        cache_settings=cache_settings,
        auto_chunk_members=False,
    )


def create_redis() -> Redis[bytes]:
    redis_url = os.getenv("REDIS_URL")
    return Redis.from_url(
        redis_url if redis_url is not None else "redis://localhost:6379"
    )


def setup_logs() -> None:
    levels = {"cleaner": logging.DEBUG}
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)
