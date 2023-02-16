import time
import typing


def backoff(delay: float = 10) -> typing.Generator[float, None, None]:
    last = 0.0
    while True:
        now = time.monotonic()
        yield max(0, delay - now + last)
        last = now
