import typing

import hikari

from ...guild import CleanerGuild


THRESHOLD = 3


class AttachmentMitigation(typing.NamedTuple):
    sizes: set[int]


def match(mitigation: AttachmentMitigation, message: hikari.Message) -> bool:
    return any(attach.size in mitigation.sizes for attach in message.attachments)


def detection(
    message: hikari.Message, messages: list[hikari.Message], guild: CleanerGuild
):
    if not message.attachments or len(messages) + 1 < THRESHOLD:
        return

    attachs = 0.0
    attachs_sizes = {k.size for k in message.attachments}
    for old_message in messages:
        if all(attach.size not in attachs_sizes for attach in old_message.attachments):
            continue
        is_exception = old_message.channel_id in guild.config.slowmode_exceptions
        value = 0.2 if is_exception else 1
        attachs += value

    if attachs >= THRESHOLD:
        return AttachmentMitigation(attachs_sizes)
