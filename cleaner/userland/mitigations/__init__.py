import typing

import hikari

from .._types import ConfigType
from . import attachment, exact, similar, sticker, token


class MitigationSystem(typing.NamedTuple):
    name: str
    match: typing.Callable[[typing.Any, hikari.Message], bool]
    detection: typing.Callable[
        [hikari.Message, typing.Sequence[hikari.Message], ConfigType],
        None | typing.Any,
    ]
    ttl: int
    block: bool


mitigations = [
    MitigationSystem("traffic.similar", similar.match, similar.detection, 120, True),
    MitigationSystem("traffic.token", token.match, token.detection, 120, True),
    MitigationSystem("traffic.exact", exact.match, exact.detection, 0, False),
    MitigationSystem("traffic.sticker", sticker.match, sticker.detection, 0, True),
    MitigationSystem(
        "traffic.attachment", attachment.match, attachment.detection, 0, True
    ),
]
mitigationsd = {mit.name: mit for mit in mitigations}
