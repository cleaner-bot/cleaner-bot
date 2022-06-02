import hikari
from cleaner_i18n import Message

from ...shared.event import IGuildEvent
from ..guild import CleanerGuild
from ..helper import action_challenge, action_delete, announcement, is_moderator
from .rules import firewall_rules


def check_message(
    event: hikari.GuildMessageCreateEvent | hikari.GuildMessageUpdateEvent,
    guild: CleanerGuild,
) -> tuple[IGuildEvent | None, ...] | None:
    data = guild.get_data()
    if not event.member or is_moderator(guild, event.member) or data is None:
        return None

    matched_rule = matched_action = None
    channel_id = str(event.channel_id)
    for rule in firewall_rules:
        config_name = rule.name.replace(".", "_")
        action = getattr(data.config, f"rules_{config_name}")
        channels = getattr(data.config, f"rules_{config_name}_channels")
        if action == 0 or channel_id in channels:
            continue
        elif matched_rule is not None and action < 2:
            continue

        if rule.func(event.message, guild):
            matched_rule = rule
            matched_action = action
            if action == 2:
                break

    if matched_rule is None:
        return None

    reason = Message("components_firewall", {"rule": matched_rule.name})
    translated = Message(
        f"components_firewall_{matched_rule.name.replace('.', '_')}",
        {"user": event.author_id},
    )
    channel = event.get_channel()
    info = {"rule": matched_rule.name}
    return (
        action_delete(event.member, event.message, reason=reason, info=info),
        action_challenge(
            guild, event.member, reason=reason, info=info, block=matched_action == 1
        ),
        announcement(channel, translated, 15) if channel is not None else None,
    )


listeners = [
    (hikari.GuildMessageCreateEvent, check_message),
    (hikari.GuildMessageUpdateEvent, check_message),
]
