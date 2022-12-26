import typing

import hikari

from .._types import ConfigType

THRESHOLD = 3


class AttachmentMitigation(typing.NamedTuple):
    sizes: set[int]


def match(mitigation: AttachmentMitigation, message: hikari.Message) -> bool:
    return any(attach.size in mitigation.sizes for attach in message.attachments)


def detection(
    message: hikari.Message,
    messages: typing.Sequence[hikari.Message],
    config: ConfigType,
) -> None | AttachmentMitigation:
    if not message.attachments or len(messages) + 1 < THRESHOLD:
        return None

    slowmode_exceptions = set(map(int, config["slowmode_exceptions"]))

    attachments = 0.0
    attachment_sizes = {k.size for k in message.attachments}
    for old_message in messages:
        if all(
            attach.size not in attachment_sizes for attach in old_message.attachments
        ):
            continue
        is_exception = old_message.channel_id in slowmode_exceptions
        value = 0.2 if is_exception else 1
        attachments += value

    if attachments >= THRESHOLD:
        return AttachmentMitigation(attachment_sizes)
    return None
