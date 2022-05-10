import hikari
from cleaner_i18n.translate import Message

from ...shared.custom_events import SlowTimerEvent
from ..guild import CleanerGuild
from ..helper import action_challenge

DAY = 24 * 3600
mode_timespans = (DAY, 3 * DAY, 7 * DAY)


def on_member_create(event: hikari.MemberCreateEvent, cguild: CleanerGuild):
    data = cguild.get_data()
    if data is None or not data.config.antiraid_enabled:
        return
    limit, timeframe = map(int, data.config.antiraid_limit.split("/"))

    cguild.member_joins.expires = cguild.member_kicks.expires = timeframe
    cguild.member_joins.add(event.user_id)
    if event.user_id in cguild.member_kicks:
        cguild.member_kicks.remove(event.user_id)

    joiners = cguild.member_joins.copy()

    matching = joiners
    if data.config.antiraid_mode > 0:
        timespan = mode_timespans[data.config.antiraid_mode - 1]
        matching = set(
            x
            for x in matching
            if abs((x.created_at - event.user_id.created_at).total_seconds()) < timespan
        )

    if len(matching) < limit:
        return

    reason = Message("components_antiraid_limit", {"limit": data.config.antiraid_limit})
    info = {
        "name": "antiraid_limit",
        "id": event.user_id,
        "username": event.user.username,
        "avatar": event.user.avatar_hash,
        "flags": event.user.flags,
    }

    actions = []

    action = action_challenge(cguild, event.member, reason=reason, info=info)
    if action.can_role or action.can_timeout:
        action = action._replace(can_role=False, can_timeout=False)

    cguild.member_kicks.add(event.user_id)

    actions.append(action)

    guild = event.get_guild()
    if guild is not None:
        for match in matching:
            if match == event.user_id:
                continue
            elif match in cguild.member_kicks:
                continue
            member = guild.get_member(match)
            if member is None:
                continue
            action = action_challenge(cguild, member, reason=reason, info=info)
            if action.can_role or action.can_timeout:
                action = action._replace(can_role=False, can_timeout=False)
            actions.append(action)

    return actions


def on_slow_timer(event: SlowTimerEvent, guild: CleanerGuild):
    guild.member_joins.evict()


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
    (SlowTimerEvent, on_slow_timer),
]
