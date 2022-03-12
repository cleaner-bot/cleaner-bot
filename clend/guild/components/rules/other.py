import re

import emoji  # type: ignore
import hikari

from cleaner_data.url import get_urls

from ...guild import CleanerGuild


emoji_regex = re.compile(r"(<a?:[^\s:]+:\d+>)|(:[^\s:]+:)")


def emoji_mass(message: hikari.Message, guild: CleanerGuild) -> bool:
    config = guild.get_config()
    if not message.content or (
        config is not None and message.channel_id in config.slowmode_exceptions
    ):
        return False
    content = emoji.demojize(message.content)
    emojis = emoji_regex.findall(content)
    return len(emojis) >= 7


def selfbot_embed(message: hikari.Message, guild: CleanerGuild) -> bool:
    if not message.content or not message.embeds:
        return False
    for _ in get_urls(message.content):
        return False
    return True
