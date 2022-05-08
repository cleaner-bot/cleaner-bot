import typing

from cleaner_conf.guild import GuildConfig, GuildEntitlements


__all__ = ["GuildData", "GuildConfig", "GuildEntitlements"]


class GuildData(typing.NamedTuple):
    config: GuildConfig
    entitlements: GuildEntitlements
