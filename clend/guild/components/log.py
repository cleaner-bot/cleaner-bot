import hikari


from ..guild import CleanerGuild
from ...shared.risk import calculate_risk_score
from ...shared.event import ILog, Translateable


def on_member_create(event: hikari.MemberCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if config is None or not config.logging_enabled or not config.logging_option_join:
        return
    age = event.member.joined_at - event.member.created_at
    hours = age.total_seconds() // 3600
    age_string = f"{age.days} days" if hours >= 48 else f"{hours} hours"
    risk = calculate_risk_score(event.user)

    return (
        ILog(
            event.guild_id,
            Translateable(
                "components_log_join",
                {"user": event.user_id, "age": age_string, "risk": int(risk * 100)},
            ),
        ),
    )


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
]
