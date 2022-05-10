import statistics
import typing

import hikari
from cleaner_data.normalize import normalize

from ...guild import CleanerGuild

MIN_DATA = 10


class TokenMessageMitigation(typing.NamedTuple):
    tokens: set[str]


def match(mitigation: TokenMessageMitigation, message: hikari.Message):
    if not message.content:
        return
    all_tokens = set(normalize(message.content, remove_urls=False).split())
    return all_tokens & mitigation.tokens == mitigation.tokens


def detection(
    message: hikari.Message,
    messages: typing.Sequence[hikari.Message],
    guild: CleanerGuild,
):
    if not message.content or len(messages) < MIN_DATA:
        return

    data = guild.get_data()
    slowmode_exceptions = (
        set() if data is None else set(map(int, data.config.slowmode_exceptions))
    )

    all_tokens = set(normalize(message.content, remove_urls=False).split())
    if not all_tokens:
        return
    scores = []
    for old_message in messages:
        if not old_message.content:
            continue
        is_exception = old_message.channel_id in slowmode_exceptions
        tokens = set(normalize(old_message.content, remove_urls=False).split())
        score = len(all_tokens & tokens) / len(all_tokens)
        scores.append((score, tokens, 0.1 if is_exception else 1))

    if len(scores) < MIN_DATA:
        return

    # standard score
    median = statistics.median(x[0] for x in scores)
    if median < 10 / len(scores):
        return
    scores = [x for x in scores if x[0] >= median]
    if sum(x[2] for x in scores) < 7:
        return

    for _, tokens, _ in scores:
        all_tokens &= tokens

    if all_tokens:
        return TokenMessageMitigation(all_tokens)
