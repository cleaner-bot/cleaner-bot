import time

import hikari

from cleaner_i18n.translate import Message

from ..guild import CleanerGuild
from ..helper import action_challenge
from ...shared.custom_events import FastTimerEvent


def on_member_create(event: hikari.MemberCreateEvent, guild: CleanerGuild):
    guild.verification_joins[event.user_id] = time.monotonic()


def on_member_delete(event: hikari.MemberDeleteEvent, guild: CleanerGuild):
    if event.user_id in guild.verification_joins:
        del guild.verification_joins[event.user_id]


def on_fast_timer(event: FastTimerEvent, cguild: CleanerGuild):
    config = cguild.get_config()
    guild = event.app.cache.get_guild(cguild.id)
    if config and config.verification_enabled:
        print(guild)
    if config is None or not config.verification_enabled or guild is None:
        return

    now = time.monotonic()
    actions = []

    info = {"name": "verification", "action": "kick"}

    print(cguild.verification_joins)
    for user_id, expire in tuple(cguild.verification_joins.items()):
        print(user_id, expire + 8 * 60 - now)
        if now < expire + 8 * 60:
            continue
        del cguild.verification_joins[user_id]

        member = guild.get_member(user_id)
        print(member)
        # > 1 because everyone role
        if member is None or len(member.role_ids) > 1:
            continue

        message = Message("verification_kick_reason", {"user": user_id})
        action = action_challenge(cguild, member, info=info, reason=message)

        if action.can_role or action.can_timeout:
            action = action._replace(can_role=False, can_timeout=False)
        actions.append(action)

    return actions


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
    (hikari.MemberDeleteEvent, on_member_delete),
    (FastTimerEvent, on_fast_timer),
]
