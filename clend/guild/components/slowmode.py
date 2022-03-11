import hikari

from ..guild import CleanerGuild


def on_message_create(event: hikari.GuildMessageCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if config is None or not config.slowmode_enabled:
        return


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
]
