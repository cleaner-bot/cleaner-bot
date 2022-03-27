import hikari

from cleaner_data.name import is_name_blacklisted
from cleaner_data.normalize import normalize
from cleaner_data.auto.avatars import data as avatar_blacklist
from cleaner_i18n.translate import Message

from ..guild import CleanerGuild
from ..helper import action_challenge


def on_member_create(event: hikari.MemberCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if config is None:
        return
    entitlements = guild.get_entitlements()

    reason: Message | None = None
    name: str | None = None

    if config.impersonation_discord and (
        is_name_blacklisted(event.user.username)
        or event.user.avatar_hash in avatar_blacklist
    ):
        reason = Message("components_impersonation_discord", {})
        name = "impersonation_discord"

    if (
        entitlements is not None
        and entitlements.impersonation_advanced >= entitlements.plan
        and config.impersonation_advanced_enabled
        and is_custom_blacklist(
            event.user.username,
            config.impersonation_advanced_words,
            config.impersonation_advanced_subwords,
        )
    ):
        reason = Message("components_impersonation_blacklist", {})
        name = "impersonation_custom_blacklist"

    if reason is None or name is None:
        return

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
        if subword in name:
            return True
    split_name = name.split()
    for word in words:
        if word in split_name:
            return True
    return False


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
]
