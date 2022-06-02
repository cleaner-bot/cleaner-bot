import typing

import hikari

from ...guild import CleanerGuild

THRESHOLD = 3


class ExactMessageMitigation(typing.NamedTuple):
    message: str


def match(mitigation: ExactMessageMitigation, message: hikari.Message) -> bool:
    return message.content == mitigation.message


def detection(
    message: hikari.Message,
    messages: typing.Sequence[hikari.Message],
    guild: CleanerGuild,
) -> None | ExactMessageMitigation:
    if not message.content or len(messages) + 1 < THRESHOLD:
        return None

    channels = {message.channel_id}
    for old_message in messages:
        if message.content == old_message.content:
            channels.add(old_message.channel_id)

    if len(channels) >= THRESHOLD:
        return ExactMessageMitigation(message.content)
    return None
