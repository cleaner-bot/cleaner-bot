import hikari

from cleaner_i18n.translate import Message

from ..guild import CleanerGuild
from ..helper import action_challenge
from ...shared.custom_events import SlowTimerEvent


def on_member_create(event: hikari.MemberCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if config is None or not config.antiraid_enabled:
        return
    limit, timeframe = map(int, config.antiraid_limit.split("/"))

    guild.member_joins.expires = timeframe
    guild.member_joins.increase()

    if guild.member_joins.value() < limit:
        return

    reason = Message("components_antiraid_limit", {"limit": config.antiraid_limit})
    info = {
        "name": "antiraid_limit",
        "id": event.user_id,
        "username": event.user.username,
        "avatar": event.user.avatar_hash,
        "flags": event.user.flags,
    }

    action = action_challenge(guild, event.member, reason=reason, info=info)
    if action.can_role or action.can_timeout:
        action = action._replace(can_role=False, can_timeout=False)

    return (action,)


def on_slow_timer(event: SlowTimerEvent, guild: CleanerGuild):
    guild.member_joins.evict()


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
    (SlowTimerEvent, on_slow_timer),
]
