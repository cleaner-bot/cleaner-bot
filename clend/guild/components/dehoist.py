import hikari
from cleaner_i18n.translate import Message

from ..guild import CleanerGuild
from ..helper import action_nickname, is_moderator


def on_member_update(event: hikari.MemberUpdateEvent, guild: CleanerGuild):
    data = guild.get_data()
    if (
        data is None
        or not data.config.general_dehoisting_enabled
        or not event.member.display_name.startswith("!")
        or is_moderator(guild, event.member)
    ):
        return

    reason = Message("components_dehoist", {})
    nickname: str | None = event.member.display_name.lstrip("!")
    # empty display_name, contains only "!"
    if not nickname:
        # if username doesn't start with "!", reset nickname
        if event.member.username.startswith("!"):
            nickname = event.member.username.lstrip("!")
            # if username is also only "!", change to "dehoisted"
            if not nickname:
                nickname = "dehoisted"
        else:
            nickname = None

    info = {
        "name": "dehoist",
        "username": event.member.username,
        "nickname": event.member.nickname,
        "new_nickname": nickname,
    }

    return (action_nickname(event.member, nickname, reason=reason, info=info),)


listeners = [
    (hikari.MemberUpdateEvent, on_member_update),
]
