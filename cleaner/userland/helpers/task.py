import asyncio
import logging
import typing

from .backoff import backoff

logger = logging.getLogger(__name__)
K = typing.TypeVar("K")
ReturnValue = typing.TypeVar("ReturnValue")


def complain_if_none(binding: K, name: str) -> K:
    if binding is None:
        logger.debug(f"failed to get {name!r}")
    return binding


async def safe_call(
    coro: typing.Awaitable[ReturnValue],
    name: str | None = None,
) -> ReturnValue | None:
    if name is None:
        name = get_name_from_coro(coro)

    try:
        return await coro
    except Exception as e:
        logger.exception(f"exception in safe call: {name}", exc_info=e)
    return None


def safe_background_call(
    coro: typing.Awaitable[ReturnValue], name: str | None = None
) -> asyncio.Task[ReturnValue | None]:
    return asyncio.create_task(safe_call(coro, name), name=name)


async def ensure_running(
    func: typing.Callable[[], typing.Awaitable[None]], name: str | None = None
) -> None:
    for sleep in backoff():
        if sleep:
            logger.debug(f"delaying restart of {name} by {sleep:.3f}s")
            await asyncio.sleep(sleep)
        await safe_call(func(), name=name)


def get_name_from_coro(coro: typing.Awaitable[typing.Any]) -> str | None:
    try:
        return f"{coro.cr_code.co_filename}.{coro.__name__}"  # type: ignore
    except Exception:
        pass

    try:
        return coro.name  # type: ignore
    except Exception:
        pass

    return None


class AsyncioTaskRunnerMixin:
    _runners: list[asyncio.Task[None]]

    def __init__(self) -> None:
        super().__init__()
        self._runners = []

    def run(self, *runners: typing.Callable[[], typing.Awaitable[None]]) -> None:
        self._runners.extend(
            [
                asyncio.create_task(
                    ensure_running(x, f"{self.__class__.__name__}.{x.__name__}"),
                    name=f"TaskRunner<{self.__class__.__name__}>",
                )
                for x in runners
            ]
        )

    def on_unload(self) -> None:
        for runner in self._runners:
            runner.cancel()
