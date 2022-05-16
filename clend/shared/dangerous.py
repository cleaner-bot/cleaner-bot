import hikari

DANGEROUS_PERMISSIONS = (
    hikari.Permissions.KICK_MEMBERS
    | hikari.Permissions.BAN_MEMBERS
    | hikari.Permissions.ADMINISTRATOR
    | hikari.Permissions.MANAGE_CHANNELS
    | hikari.Permissions.MANAGE_GUILD
    | hikari.Permissions.MANAGE_MESSAGES
    | hikari.Permissions.MUTE_MEMBERS
    | hikari.Permissions.DEAFEN_MEMBERS
    | hikari.Permissions.MOVE_MEMBERS
    | hikari.Permissions.MANAGE_NICKNAMES
    | hikari.Permissions.MANAGE_ROLES
    | hikari.Permissions.MANAGE_WEBHOOKS
    | hikari.Permissions.MANAGE_EMOJIS_AND_STICKERS
    # | hikari.Permissions.MANAGE_EVENTS
    | hikari.Permissions.MANAGE_THREADS
    | hikari.Permissions.MODERATE_MEMBERS
)


def dangerous_content(message: str) -> str:
    return (
        message.replace("://", "\\://")
        .replace("discord.gg/", "discord\\.gg/")
        .replace("discord.com/invite/", "discord\\.com/invite/")
        .replace("discordapp.com/invite/", "discordapp\\.com/invite/")
    )
