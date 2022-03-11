import hikari
from cleaner_data.unicode import normalize_unicode

from ..guild import CleanerGuild
from ..helper import action_challenge


impersonation_words = {
    "developer",
    "partners",
    "exam",
    "devbot",
    "mod",
    "support",
    "intents",
    "api",
    "partner",
    "message",
    "moderator",
    "academy",
    "developers",
    "hypesquad",
    "moderators",
}


def on_member_create(event: hikari.MemberCreateEvent, guild: CleanerGuild):
    if not guild.config.overview_discordimpersonation_enabled:
        return
    name = normalize_unicode(event.member.display_name)
    words = name.split()
    if not all(w in impersonation_words for w in words):
        return

    action = action_challenge(guild, event.member, "discord-impersonation")
    if action.can_role or action.can_timeout:
        action = action._replace(can_role=False, can_timeout=False)
    return action,


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
]
