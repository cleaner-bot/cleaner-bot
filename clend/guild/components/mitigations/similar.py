import typing

import hikari
from Levenshtein import ratio  # type: ignore

from ...guild import CleanerGuild


class SimilarMessageMitigation(typing.NamedTuple):
    message: str
    match_ratio: float


THRESHOLD_USER = 4
THRESHOLD_GUILD = 11
MAX_MATCH_RATIO = 0.8


def match(mitigation: SimilarMessageMitigation, message: hikari.Message) -> bool:
    if not message.content:
        return False
    return ratio(mitigation.message, message.content) >= mitigation.match_ratio


def detection(
    message: hikari.Message, messages: list[hikari.Message], guild: CleanerGuild
):
    if not message.content or len(messages) < THRESHOLD_USER:
        return

    data = guild.get_data()
    slowmode_exceptions = (
        set() if data is None else set(map(int, data.config.slowmode_exceptions))
    )

    user_score = guild_score = 0.0
    current_match_ratio = 1.0
    for old_message in messages:
        if not old_message.content:
            continue
        r = ratio(message.content, old_message.content)
        if r < MAX_MATCH_RATIO:
            continue

        if r < current_match_ratio:
            current_match_ratio = r

        is_exception = old_message.channel_id in slowmode_exceptions
        score = 0.1 if is_exception else 1

        guild_score += score
        if message.author.id == old_message.author.id:
            user_score += score

    if guild_score >= THRESHOLD_GUILD or user_score >= THRESHOLD_USER:
        return SimilarMessageMitigation(message.content, current_match_ratio)
