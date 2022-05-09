import asyncio
import logging
import time

logger = logging.getLogger(__name__)


async def protect(coro, *args, **kwargs):
    last_failure = 0
    while True:
        try:
            await coro(*args, **kwargs)
        except Exception as e:
            now = time.monotonic()
            diff = now - last_failure
            logger.exception("Error in protected task", exc_info=e)
            if diff < 0.1:
                logger.warning(
                    "error occured within 100ms, sleeping 100ms before retrying"
                )
                await asyncio.sleep(0.1)
                now = time.monotonic()
            last_failure = now
        else:
            break


async def protected_call(coro):
    try:
        return await coro
    except Exception as e:
        logger.exception("Error in protected call", exc_info=e)
