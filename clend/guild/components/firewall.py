import hikari

from .rules import firewall_rules
from ..guild import CleanerGuild
from ..helper import action_delete, action_challenge, is_moderator


def on_message_create(event: hikari.GuildMessageCreateEvent, guild: CleanerGuild):
    if event.member is None or is_moderator(guild, event.member):
        return

    matched_rule = matched_action = None
    for rule in firewall_rules:
        config_name = rule.name.replace(".", "_")
        action = getattr(guild.config, f"rules_{config_name}")
        if action == 0:
            continue
        elif matched_rule is not None and action < 2:
            continue

        if rule.func(event.message, guild):
            matched_rule = rule
            matched_action = action
            if action == 2:
                break

    if matched_rule is None:
        return

    return [
        action_delete(
            event.member,
            event.message,
            f"firewall {matched_rule.name}",
        ),
        action_challenge(
            guild,
            event.member,
            f"firewall {matched_rule.name}",
            block=matched_action == 1,
        ),
    ]


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
]
