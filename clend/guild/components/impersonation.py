import hikari
from cleaner_data.auto.avatars import data as avatar_blacklist
from cleaner_data.name import is_name_blacklisted
from cleaner_data.normalize import normalize
from cleaner_i18n import Message
from hikari.internal.time import utc_datetime

from ...shared.event import IActionChallenge
from ..guild import CleanerGuild
from ..helper import action_challenge


def on_new_member(
    event: hikari.MemberCreateEvent | hikari.MemberUpdateEvent, guild: CleanerGuild
) -> tuple[IActionChallenge] | None:
    data = guild.get_data()
    if data is None or (
        isinstance(event, hikari.MemberUpdateEvent)  # prevent duplicate actions
        and (
            event.old_member is None
            or event.old_member.username == event.member.username
        )
        and (event.member.joined_at - utc_datetime()).total_seconds() < 5
    ):
        return None

    reason: Message | None = None
    name: str | None = None

    if (
        data.config.impersonation_discord_enabled
        and (
            is_name_blacklisted(event.user.username)
            or event.user.avatar_hash in avatar_blacklist
        )
        and (
            event.user.avatar_hash is None
            or not event.user.avatar_hash.startswith("a_")
        )
    ):
        reason = Message("components_impersonation_discord", {})
        name = "impersonation_discord"

    if (
        data.entitlements.plan >= data.entitlements.impersonation_advanced
        and data.config.impersonation_advanced_enabled
        and is_custom_blacklist(
            event.user.username,
            data.config.impersonation_advanced_words,
            data.config.impersonation_advanced_subwords,
        )
    ):
        reason = Message("components_impersonation_blacklist", {})
        name = "impersonation_custom_blacklist"

    if reason is None or name is None:
        return None

    info = {
        "name": name,
        "id": event.user_id,
        "username": event.user.username,
        "avatar": event.user.avatar_hash,
        "flags": event.user.flags,
    }

    action = action_challenge(guild, event.member, reason=reason, info=info)
    if action.can_role or action.can_timeout:
        action = action._replace(can_role=False, can_timeout=False)

    return (action,)


def is_custom_blacklist(name: str, words: list[str], subwords: list[str]) -> bool:
    name = normalize(name)
    for subword in subwords:
        if normalize(subword) in name:
            return True
    split_name = name.split()
    for word in words:
        if normalize(word) in split_name:
            return True
    return False


listeners = [
    (hikari.MemberCreateEvent, on_new_member),
    (hikari.MemberUpdateEvent, on_new_member),
]
