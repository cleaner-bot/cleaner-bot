import statistics
import typing
import logging

import hikari
from decancer_py import parse

from .._types import ConfigType
from ..helpers.tokenizer import tokenize

logger = logging.getLogger(__name__)
MIN_DATA = 10


class TokenMessageMitigation(typing.NamedTuple):
    tokens: set[str]


def match(mitigation: TokenMessageMitigation, message: hikari.Message) -> bool:
    if not message.content:
        return False
    all_tokens = set(tokenize(parse(message.content)))
    return all_tokens & mitigation.tokens == mitigation.tokens


def detection(
    message: hikari.Message,
    messages: typing.Sequence[hikari.Message],
    config: ConfigType,
) -> None | TokenMessageMitigation:
    if not message.content or len(messages) < MIN_DATA:
        return None

    slowmode_exceptions = set(map(int, config["slowmode_exceptions"]))

    all_tokens = set(tokenize(parse(message.content)))
    if not all_tokens:
        return None
    scores = []
    for old_message in messages:
        if not old_message.content:
            continue
        is_exception = old_message.channel_id in slowmode_exceptions
        tokens = set(tokenize(parse(old_message.content)))
        score = len(all_tokens & tokens) / len(all_tokens)
        scores.append((score, tokens, 0.1 if is_exception else 1))

    if len(scores) < MIN_DATA:
        return None

    # standard score
    median = statistics.median(x[0] for x in scores)
    if median < 10 / len(scores):
        return None
    scores = [x for x in scores if x[0] >= median]
    if sum(x[2] for x in scores) < 7:
        return None

    for _, tokens, _ in scores:
        all_tokens &= tokens

    if all_tokens:
        logger.debug(f"tokens: {all_tokens}")
        return TokenMessageMitigation(all_tokens)
    return None
