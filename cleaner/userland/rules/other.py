import re

import emoji  # type: ignore
import hikari

from .._types import KernelType
from ..helpers.url import get_urls

emoji_regex = re.compile(r"(<a?:[^\s:]+:\d+>)|(:[^\s:]+:)")


def emoji_mass(kernel: KernelType, message: hikari.PartialMessage) -> bool:
    if not message.content:
        return False
    content = emoji.demojize(message.content)
    emojis = emoji_regex.findall(content)
    return len(emojis) >= 7


def selfbot_embed(kernel: KernelType, message: hikari.PartialMessage) -> bool:
    if not message.content or not message.embeds:
        return False
    for _ in get_urls(message.content):
        return False
    return True
