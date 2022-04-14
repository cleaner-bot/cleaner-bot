from datetime import datetime
import typing
from pathlib import Path

import msgpack  # type: ignore


DEFAULT = Path("metrics.bin")


class Metrics:
    history: list[tuple[int, typing.Any]]
    _entries: list[bytes]
    _file: typing.TextIO | None = None

    def __init__(self, path: Path = None):
        if path is None:
            path = DEFAULT
        self.path = path
        self.history = []
        self._entries = []

    def _open(self):
        if self._file is None:
            if not self.path.parent.exists():
                self.path.parent.mkdir(parents=True)
            self._file = self.path.open("ab")

    def close(self):
        if self._file is not None:
            self._file.close()

    def __del__(self):
        self.flush()
        self.close()

    def log(self, info):
        payload = (datetime.utcnow().timestamp(), info)
        self.history.append(payload)
        self._entries.append(msgpack.packb(payload))

    def flush(self):
        if self._entries:
            if self._file is None:
                self._open()
            while self._entries:
                self._file.write(self._entries.pop(0))
            self._file.flush()


def metrics_reader(path: Path = None):
    if path is None:
        path = DEFAULT
    if not path.exists():
        return
    extra = path.read_bytes()
    while extra:
        try:
            yield msgpack.unpackb(extra, use_list=False)
        except msgpack.ExtraData as e:
            extra = e.extra
            yield e.unpacked
        else:
            break
