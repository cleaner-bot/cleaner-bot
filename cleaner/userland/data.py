import json
import logging
from pathlib import Path

from ._types import KernelType

logger = logging.getLogger(__name__)


class DataService:
    path = Path() / "data"
    changed: set[str]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.bindings["data:load"] = self.load_data
        self.kernel.bindings["data:save"] = self.save_data
        self.kernel.bindings["data:changed"] = self.mark_changed
        self.changed = set()
        self.load_data()

    def load_data(self, name: str | None = None) -> bool | None:
        if name is None:
            for file in self.path.iterdir():
                if file.name.startswith(".") or not file.name.endswith(".json"):
                    continue
                self.load_data(file.name[:-5])
            return None

        logger.debug(f"loading {name}")

        file = self.path / f"{name}.json"
        if not file.exists() or not file.is_file():
            logger.warning(f"trying to load data {name!r}, but it doesnt exist")
            return False

        content = file.read_text()
        try:
            data = json.loads(content)
        except ValueError as e:
            logger.exception(
                f"trying to load data {name!r}, but it contains bad data", exc_info=e
            )
            return False

        self.kernel.data[name] = data  # type: ignore
        return True

    def save_data(self, name: str | None = None) -> bool | None:
        if name is None:
            for name in self.changed:
                self.save_data(name)
            self.changed.clear()
            return None

        logger.debug(f"saving {name}")

        data = self.kernel.data[name]  # type: ignore
        file = self.path / f"{name}.json"
        file.write_text(json.dumps(data, indent=2))
        return True

    def mark_changed(self, name: str) -> None:
        self.changed.add(name)

    def on_unload(self) -> None:
        self.save_data()
