import typing

import hikari

from . import similar, exact, token, sticker
from ...guild import CleanerGuild


class MitigationSystem(typing.NamedTuple):
    name: str
    match: typing.Callable[[typing.Any, hikari.Message], bool]
    detection: typing.Callable[
        [hikari.Message, list[hikari.Message], CleanerGuild], None | typing.Any
    ]
    ttl: int


mitigations = [
    MitigationSystem("traffic.similar", similar.match, similar.detection, 120),
    MitigationSystem("traffic.exact", exact.match, exact.detection, 120),
    MitigationSystem("traffic.token", token.match, token.detection, 120),
    MitigationSystem("traffic.sticker", sticker.match, sticker.detection, 0),
]
mitigationsd = {mit.name: mit for mit in mitigations}
