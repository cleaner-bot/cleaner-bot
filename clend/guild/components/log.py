from datetime import datetime

import hikari

from cleaner_i18n.translate import Message

from ..guild import CleanerGuild
from ...shared.risk import calculate_risk_score
from ...shared.event import ILog


def on_member_create(event: hikari.MemberCreateEvent, guild: CleanerGuild):
    data = guild.get_data()
    if (
        data is None
        or not data.config.logging_enabled
        or not data.config.logging_option_join
    ):
        return
    age = event.member.joined_at - event.member.created_at
    hours = age.total_seconds() // 3600
    risk = calculate_risk_score(event.user)

    return (
        ILog(
            event.guild_id,
            Message(
                "components_log_join_" + ("day" if hours >= 48 else "hour"),
                {
                    "user": event.user_id,
                    "name": str(event.user),
                    "age": age.days if hours >= 48 else hours,
                    "risk": int(risk * 100),
                },
            ),
            event.member.joined_at,
        ),
    )


def on_member_delete(event: hikari.MemberDeleteEvent, guild: CleanerGuild):
    data = guild.get_data()
    if (
        data is None
        or not data.config.logging_enabled
        or not data.config.logging_option_leave
    ):
        return

    return (
        ILog(
            event.guild_id,
            Message(
                "components_log_leave",
                {"user": event.user_id, "name": str(event.user)},
            ),
            datetime.utcnow(),
        ),
    )


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
    (hikari.MemberDeleteEvent, on_member_delete),
]
