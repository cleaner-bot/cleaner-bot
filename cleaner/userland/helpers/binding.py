import asyncio
import logging
import typing

logger = logging.getLogger(__name__)
K = typing.TypeVar("K")
ReturnValue = typing.TypeVar("ReturnValue")


def complain_if_none(binding: K, name: str) -> K:
    if binding is None:
        logger.debug(f"tried to get binding {name!r}, but it wasn't loaded")
    return binding


async def safe_call(
    coro: typing.Awaitable[ReturnValue], run_in_background: bool = False
) -> ReturnValue | None:
    if run_in_background:
        name = None
        try:
            name = f"{coro.cr_code.co_filename}.{coro.__name__}"  # type: ignore
        except Exception:
            try:
                name = coro.name  # type: ignore
            except Exception:
                pass

        asyncio.create_task(safe_call(coro), name=name)
        return None

    try:
        return await coro
    except Exception as e:
        logger.exception("exception in safe call", exc_info=e)
    return None
