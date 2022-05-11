import re

import emoji  # type: ignore
import hikari
from cleaner_data.url import get_urls

from ...guild import CleanerGuild
from ...helper import is_exception

emoji_regex = re.compile(r"(<a?:[^\s:]+:\d+>)|(:[^\s:]+:)")


def emoji_mass(message: hikari.PartialMessage, guild: CleanerGuild) -> bool:
    if not message.content or is_exception(guild, message.channel_id):
        return False
    content = emoji.demojize(message.content)
    emojis = emoji_regex.findall(content)
    return len(emojis) >= 7


def selfbot_embed(message: hikari.PartialMessage, guild: CleanerGuild) -> bool:
    if not message.content or not message.embeds:
        return False
    for _ in get_urls(message.content):
        return False
    return True
