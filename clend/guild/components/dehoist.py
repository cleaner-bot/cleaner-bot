import hikari

from ..guild import CleanerGuild
from ..helper import action_nickname, is_moderator


def on_member_update(event: hikari.MemberUpdateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if config is None or not config.overview_dehoisting_enabled:
        return
    if event.member.username == event.member.nickname:
        return
    if not event.member.display_name.startswith("!"):
        return
    if is_moderator(guild, event.member):
        return

    return (action_nickname(event.member, "dehoist"),)


listeners = [
    (hikari.MemberUpdateEvent, on_member_update),
]
