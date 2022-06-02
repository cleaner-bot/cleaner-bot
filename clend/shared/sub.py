import logging
import typing

from coredis.commands.pubsub import PubSub

logger = logging.getLogger(__name__)


class Message(typing.NamedTuple):
    data: bytes
    channel: bytes
    is_pattern: bool


class Subscribe(typing.NamedTuple):
    data: bytes
    channel: bytes
    is_pattern: bool


class Unsubscribe(typing.NamedTuple):
    data: bytes
    channel: bytes
    is_pattern: bool


async def listen(
    pubsub: PubSub[bytes], /, timeout: int | float = 0
) -> typing.AsyncGenerator[Message | Subscribe | Unsubscribe, None]:
    while True:
        message = await pubsub.get_message(timeout=timeout)
        if message is None:
            break
        is_pattern = message["type"].startswith("p")
        type = message["type"][1:] if is_pattern else message["type"]

        if type == "subscribe":
            yield Subscribe(
                message["data"], message["channel"], is_pattern  # type: ignore
            )
        elif type == "unsubscribe":
            yield Unsubscribe(
                message["data"], message["channel"], is_pattern  # type: ignore
            )
        elif type == "message":
            yield Message(
                message["data"], message["channel"], is_pattern  # type: ignore
            )
        else:
            logger.warning(f"received unknown type on pubsub: {type} ({is_pattern})")
