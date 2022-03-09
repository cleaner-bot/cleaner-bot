import typing

import hikari

from ...guild import CleanerGuild


THRESHOLD = 3


class ExactMessageMitigation(typing.NamedTuple):
    message: str


def match(mitigation: ExactMessageMitigation, message: hikari.Message):
    return message.content == mitigation.message


def detection(
    message: hikari.Message, messages: list[hikari.Message], guild: CleanerGuild
):
    if not message.content or len(messages) + 1 < THRESHOLD:
        return

    channels = {message.channel_id}
    for old_message in messages:
        if message.content == old_message.content:
            channels.add(message.channel_id)

    if len(channels) >= THRESHOLD:
        return ExactMessageMitigation(message.content)
