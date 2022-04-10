import hikari

from cleaner_i18n.translate import Message

from ..guild import CleanerGuild
from ..helper import action_nickname, is_moderator


def on_member_update(event: hikari.MemberUpdateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if (
        config is None
        or not config.general_dehoisting_enabled
        or event.member.username == event.member.nickname
        or not event.member.display_name.startswith("!")
        or is_moderator(guild, event.member)
    ):
        return

    reason = Message("components_dehoist", {})
    info = {
        "name": "dehoist",
        "username": event.member.username,
        "nickanme": event.member.nickname,
    }
    return (action_nickname(event.member, reason=reason, info=info),)


listeners = [
    (hikari.MemberUpdateEvent, on_member_update),
]
