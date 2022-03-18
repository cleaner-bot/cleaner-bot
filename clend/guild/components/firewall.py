import hikari

from .rules import firewall_rules
from ..guild import CleanerGuild
from ..helper import action_delete, action_challenge, is_moderator, announcement
from ...shared.event import Translateable


def on_message_create(event: hikari.GuildMessageCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if event.member is None or is_moderator(guild, event.member) or config is None:
        return

    matched_rule = matched_action = None
    for rule in firewall_rules:
        config_name = rule.name.replace(".", "_")
        action = getattr(config, f"rules_{config_name}")
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

    reason = Translateable("components_firewall", {"rule": matched_rule.name})
    translated = Translateable(f"components_firewall_{matched_rule.name.replace('.', '_')}", {"user": event.author_id})
    info = {"rule": matched_rule.name}
    return (
        action_delete(event.member, event.message, reason=reason, info=info),
        action_challenge(
            guild, event.member, reason=reason, info=info, block=matched_action == 1
        ),
        announcement(event.get_channel(), translated, 15),
    )


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
]
