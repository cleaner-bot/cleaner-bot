import hikari

from ..guild import CleanerGuild


def on_message_create(event: hikari.GuildMessageCreateEvent, guild: CleanerGuild):
    if not guild.config.slowmode_enabled:
        return


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
]
