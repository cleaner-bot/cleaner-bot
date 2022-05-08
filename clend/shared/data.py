import typing

from cleaner_conf.guild import GuildConfig, GuildEntitlements


__all__ = ["GuildData", "GuildConfig", "GuildEntitlements"]


class GuildWorker:
    __slots__ = ("source",)
    source: str

    def __init__(self, source: str = "") -> None:
        self.source = source


class GuildData(typing.NamedTuple):
    config: GuildConfig
    entitlements: GuildEntitlements
    worker: GuildWorker
