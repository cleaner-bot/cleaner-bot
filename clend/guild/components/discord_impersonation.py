import hikari
from cleaner_data.name import is_name_blacklisted
from cleaner_data.auto.avatars import data as avatar_blacklist

from ..guild import CleanerGuild
from ..helper import action_challenge
from ...shared.event import Translateable


def on_member_create(event: hikari.MemberCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if (
        config is None
        or not config.overview_discordimpersonation_enabled
        or not is_name_blacklisted(event.user.username)
        or event.user.avatar_hash not in avatar_blacklist
    ):
        return

    reason = Translateable("components_discordimpersonation", {})
    info = {
        "name": "discord_impersonation",
        "id": event.user_id,
        "username": event.user.username,
        "avatar": event.user.avatar_hash,
        "flags": event.user.flags,
    }
    action = action_challenge(guild, event.member, reason=reason, info=info)
    if action.can_role or action.can_timeout:
        action = action._replace(can_role=False, can_timeout=False)

    return (action,)


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
]
