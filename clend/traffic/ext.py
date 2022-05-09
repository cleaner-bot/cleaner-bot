import logging
import typing
from pathlib import Path

import hikari

from ..app import TheCleanerApp
from .scoring import raw_score_message

logger = logging.getLogger(__name__)
path = Path("../traffic.txt")


class TrafficExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    data: dict[str, dict[int, int]]

    def __init__(self, app: TheCleanerApp):
        self.app = app
        self.listeners = [
            (hikari.GuildMessageCreateEvent, self.on_message_create),
        ]
        self.data = {}

    def on_load(self):
        if not path.exists():
            return
        self.data = {
            line.split(" ")[0]: {
                x.split("=")[0]: int(x.split("=")[1])
                for x in line.split(" ")[1].split(",")
            }
            for line in path.read_text().splitlines()
        }

    def on_unload(self):
        path.write_text(
            "\n".join(
                f"{key} " + ",".join(f"{k}={v}" for k, v in value.items())
                for key, value in self.data.items()
            )
        )

    async def on_message_create(self, event: hikari.GuildMessageCreateEvent):
        if event.is_bot or event.is_webhook or event.member is None:
            return
        scores = raw_score_message(event.message)
        # logger.debug(f"scores: {scores}")
        for name, score in scores.items():
            values = self.data.get(name)
            if values is None:
                values = self.data[name] = {}
            values[score] = values.get(score, 0) + 1
