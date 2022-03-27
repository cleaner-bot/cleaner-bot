import typing

import hikari

from . import advertisement, other, phishing, ping
from ...guild import CleanerGuild


class FirewallRule(typing.NamedTuple):
    name: str
    func: typing.Callable[[hikari.Message, CleanerGuild], bool]


firewall_rules = [
    FirewallRule("phishing.content", phishing.phishing_content),
    FirewallRule("phishing.domain.blacklisted", phishing.phishing_domain_blacklisted),
    FirewallRule("phishing.domain.heuristic", phishing.phishing_domain_heuristic),
    FirewallRule("phishing.embed", phishing.phishing_embed),
    FirewallRule("ping.users.many", ping.ping_users_many),
    FirewallRule("ping.users.few", ping.ping_users_few),
    FirewallRule("ping.roles", ping.ping_roles),
    FirewallRule("ping.broad", ping.ping_broad),
    FirewallRule("ping.hidden", ping.ping_hidden),
    FirewallRule("advertisement.discord.invite", advertisement.advertisement_discord),
    FirewallRule("emoji.mass", other.emoji_mass),
    FirewallRule("selfbot.embed", other.selfbot_embed),
]
