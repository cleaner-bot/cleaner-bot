import typing

import hikari

from ...guild import CleanerGuild


THRESHOLD = 3


class StickerMitigation(typing.NamedTuple):
    ids: tuple[int, ...]


def match(mitigation: StickerMitigation, message: hikari.Message) -> bool:
    return any(sticker.id in mitigation.ids for sticker in message.stickers)


def detection(
    message: hikari.Message, messages: list[hikari.Message], guild: CleanerGuild
):
    if not message.stickers or len(messages) + 1 < THRESHOLD:
        return

    config = guild.get_config()
    slowmode_exceptions = (
        set() if config is None else set(map(int, config.slowmode_exceptions))
    )

    stickers = 0.0
    stickers_ids = {int(k.id) for k in message.stickers}
    for old_message in messages:
        if all(sticker.id not in stickers_ids for sticker in old_message.stickers):
            continue
        is_exception = old_message.channel_id in slowmode_exceptions
        value = 0.2 if is_exception else 1
        stickers += value

    if stickers >= THRESHOLD:
        return StickerMitigation(tuple(stickers_ids))
