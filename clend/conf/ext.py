import typing

import hikari

from cleaner_conf import Config, Entitlements

from ..bot import TheCleaner


class GuildData(typing.NamedTuple):
    config: Config
    entitlements: Entitlements


class ConfigExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    _guilds: dict[int, GuildData]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = []

        self._guilds = {}

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

    def set(self, guild_id: int, config: Config, entitlements: Entitlements):
        self._guilds[guild_id] = GuildData(config, entitlements)
