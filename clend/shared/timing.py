from __future__ import annotations

import time
import typing
import logging
import inspect

logger = logging.getLogger(__name__)


class Checkpoint(typing.NamedTuple):
    name: str
    timestamp: float


class Timed:
    checkpoints: list[Checkpoint]
    _end_time: float | None = None

    def __init__(self, *, name: str = None, report_threshold: float = 0.05) -> None:
        self._start_time = time.monotonic()
        self.checkpoints = []
        self.name = name
        self.report_threshold = report_threshold

    def checkpoint(self, name: str):
        self.checkpoints.append(Checkpoint(name, time.monotonic()))

    def report(self) -> str:
        result = []
        for i, c in enumerate(self.checkpoints):
            other_timestamp = (
                self.checkpoints[i - 1].timestamp if i else self._start_time
            )
            result.append(f"{(c.timestamp - other_timestamp) * 1000:>3.3f} ms {c.name}")
        if self._end_time is not None:
            result.append(
                f"{(self._end_time - self._start_time) * 1000:>3.3f} ms finish"
            )
        return "\n".join(result)

    def __enter__(
        self, *, name: str | None = None, report_threshold: float | None = None
    ) -> Timed:
        if name is not None:
            self.name = name
        if report_threshold is not None:
            self.report_threshold = report_threshold

        if self.name is None:
            caller = inspect.stack()[1]
            self.name = f"{caller.filename}:{caller.lineno} {caller.function}"

        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close()

    def close(self, force_report: bool = False):
        self._end_time = time.monotonic()
        if self._end_time - self._start_time > self.report_threshold or force_report:
            report = self.report()
            logger.warning(
                f"routine took {(self._end_time - self._start_time) * 1000:.3f}ms\n"
                f"{report}"
            )
