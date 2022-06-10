import typing
from datetime import datetime
from io import BufferedWriter
from pathlib import Path

import msgpack  # type: ignore

DEFAULT = Path("metrics.bin")
Item = dict[str, typing.Any]


def set_encoder(obj: typing.Any) -> typing.Any:
    if isinstance(obj, set):
        return tuple(obj)
    return obj


class Metrics:
    history: list[tuple[float, Item]]
    _entries: list[bytes]
    _file: BufferedWriter | None = None

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = DEFAULT
        self.path = path
        self.history = []
        self._entries = []

    def _open(self) -> None:
        if self._file is None:
            if not self.path.parent.exists():
                self.path.parent.mkdir(parents=True)
            self._file = self.path.open("ab")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()

    def __del__(self) -> None:
        self.flush()
        self.close()

    def log(self, info: Item) -> None:
        payload = (datetime.utcnow().timestamp(), info)
        self.history.append(payload)
        self._entries.append(msgpack.packb(payload, default=set_encoder))

    def flush(self) -> None:
        if self._entries:
            if self._file is None:
                self._open()
            assert self._file, "impossible"
            while self._entries:
                self._file.write(self._entries.pop(0))
            self._file.flush()


def metrics_reader(
    path: Path | None = None,
) -> typing.Generator[tuple[float, Item], None, None]:
    if path is None:
        path = DEFAULT
    if path.exists():
        all_bytes = path.read_bytes()
        unpacker = msgpack.Unpacker(use_list=False)
        unpacker.feed(all_bytes)
        yield from unpacker
