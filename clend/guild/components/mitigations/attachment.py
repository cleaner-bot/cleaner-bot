import typing

import hikari

from ...guild import CleanerGuild

THRESHOLD = 3


class AttachmentMitigation(typing.NamedTuple):
    sizes: set[int]


def match(mitigation: AttachmentMitigation, message: hikari.Message) -> bool:
    return any(attach.size in mitigation.sizes for attach in message.attachments)


def detection(
    message: hikari.Message,
    messages: typing.Sequence[hikari.Message],
    guild: CleanerGuild,
) -> None | AttachmentMitigation:
    if not message.attachments or len(messages) + 1 < THRESHOLD:
        return None

    data = guild.get_data()
    slowmode_exceptions = (
        set() if data is None else set(map(int, data.config.slowmode_exceptions))
    )

    attachs = 0.0
    attachs_sizes = {k.size for k in message.attachments}
    for old_message in messages:
        if all(attach.size not in attachs_sizes for attach in old_message.attachments):
            continue
        is_exception = old_message.channel_id in slowmode_exceptions
        value = 0.2 if is_exception else 1
        attachs += value

    if attachs >= THRESHOLD:
        return AttachmentMitigation(attachs_sizes)
    return None
