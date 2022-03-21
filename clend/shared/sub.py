import typing
import logging

from coredis.commands.pubsub import PubSub  # type: ignore


logger = logging.getLogger(__name__)


class Message(typing.NamedTuple):
    data: bytes
    channel: bytes
    is_pattern: bool


class Subscribe(typing.NamedTuple):
    data: int
    channel: bytes
    is_pattern: bool


class Unsubscribe(typing.NamedTuple):
    data: int
    channel: bytes
    is_pattern: bool


async def listen(
    pubsub: PubSub, /, **kwargs
) -> typing.AsyncGenerator[Message | Subscribe | Unsubscribe, None]:
    while True:
        message = await pubsub.get_message(**kwargs)
        is_pattern = message["type"].startswith("p")
        type = message["type"][1:] if is_pattern else message["type"]

        if type == "subscribe":
            yield Subscribe(message["data"], message["channel"], is_pattern)
        elif type == "unsubscribe":
            yield Unsubscribe(message["data"], message["channel"], is_pattern)
        elif type == "message":
            yield Message(message["data"], message["channel"], is_pattern)
        else:
            logger.warning(f"received unknown type on pubsub: {type} ({is_pattern})")
