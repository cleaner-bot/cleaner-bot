import time
import typing


def timer_generator(time_func: typing.Callable[[], float] = time.monotonic):
    last = time_func()
    yield 0
    while True:
        now = time_func()
        yield now - last
        last = now
