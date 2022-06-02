import asyncio
import logging
import time
import typing

logger = logging.getLogger(__name__)
T = typing.TypeVar("T")


async def protect(
    coro: typing.Callable[..., typing.Coroutine[None, None, typing.Any]]
) -> None:
    last_failure = 0.0
    while True:
        try:
            await coro()
        except Exception as e:
            now = time.monotonic()
            diff = now - last_failure
            logger.exception("Error in protected task", exc_info=e)
            if diff < 0.1:
                logger.warning(
                    "error occured within 100ms, sleeping 1s before retrying"
                )
                await asyncio.sleep(1)
                now = time.monotonic()
            last_failure = now
        else:
            break


async def protected_call(coro: typing.Coroutine[None, None, T]) -> T | None:
    try:
        return await coro
    except Exception as e:
        logger.exception("Error in protected call", exc_info=e)
    return None
