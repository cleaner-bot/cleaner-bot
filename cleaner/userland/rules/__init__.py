import typing

import hikari

from .._types import KernelType
from . import advertisement, other, phishing, ping


class AutoModRule(typing.NamedTuple):
    name: str
    func: typing.Callable[[KernelType, hikari.PartialMessage], bool]


automod_rules = [
    AutoModRule("advertisement.unsafelink", advertisement.advertisement_unsafelink),
    AutoModRule(
        "advertisement.discord.unsafeinvite", advertisement.advertisement_unsafediscord
    ),
    AutoModRule("advertisement.discord.invite", advertisement.advertisement_discord),
    AutoModRule("phishing.content", phishing.phishing_content),
    AutoModRule("phishing.domain.blacklisted", phishing.phishing_domain_blacklisted),
    AutoModRule("phishing.domain.heuristic", phishing.phishing_domain_heuristic),
    AutoModRule("phishing.embed", phishing.phishing_embed),
    AutoModRule("ping.users.many", ping.ping_users_many),
    AutoModRule("ping.users.few", ping.ping_users_few),
    AutoModRule("ping.roles", ping.ping_roles),
    AutoModRule("ping.broad", ping.ping_broad),
    AutoModRule("ping.hidden", ping.ping_hidden),
    AutoModRule("emoji.mass", other.emoji_mass),
    AutoModRule("selfbot.embed", other.selfbot_embed),
]
