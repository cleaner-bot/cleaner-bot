from __future__ import annotations

import asyncio
import logging
import time
import typing
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import msgpack  # type: ignore

from ._types import EventType, KernelType
from .helpers.binding import safe_call

logger = logging.getLogger(__name__)


class LegacyDeleteEvent(typing.TypedDict):
    name: typing.Literal["delete"]
    rule: str
    guild: int


class LegacyNicknameEvent(typing.TypedDict):
    name: typing.Literal["nickname"]
    guild: int


class LegacyChallengeEvent(typing.TypedDict):
    name: typing.Literal["challenge"]
    action: str
    guild: int


AllEventType = (
    EventType | LegacyDeleteEvent | LegacyNicknameEvent | LegacyChallengeEvent
)


def set_encoder(obj: typing.Any) -> typing.Any:
    if isinstance(obj, set):
        return tuple(obj)
    return obj


class StatisticsService:
    statistics = Path() / "pdata" / "statistics.bin"
    new_events: list[bytes]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.new_events = []

        self.kernel.bindings["track"] = self.track
        self.kernel.bindings["statistics:save"] = self.save

    async def track(self, event: AllEventType) -> None:
        logger.debug(f"{event=}")
        data = msgpack.packb(
            (int(datetime.now().timestamp()), event), default=set_encoder
        )
        self.new_events.append(typing.cast(bytes, data))

    async def save(self) -> None:
        loop = asyncio.get_event_loop()
        if self.new_events:
            await safe_call(loop.run_in_executor(None, self.save_data))
        if not self.statistics.exists():
            logger.debug(f"no statistics available yet - {self.statistics}")
            return
        data = await safe_call(loop.run_in_executor(None, self.process_data))
        if data is None:
            return  # error occured

        guild_statistics, global_statistics = data
        for guild_id, guild_data in guild_statistics.items():
            await self.kernel.database.set(
                f"guild:{guild_id}:statistics",
                typing.cast(bytes, msgpack.packb(guild_data)),
            )

        await self.kernel.database.set(
            "statistics:global", typing.cast(bytes, msgpack.packb(global_statistics))
        )

    def save_data(self) -> None:
        start_time = time.monotonic()
        logger.debug("saving data")
        if self.new_events:
            with self.statistics.open("ab") as fd:
                fd.write(b"".join(self.new_events))
            self.new_events.clear()
        logger.debug(f"saved data in {time.monotonic() - start_time:.3f}s")

    def process_data(self) -> tuple[dict[int, Timespans], Timespans]:
        start = time.monotonic()
        logger.debug("processing statistics data")

        all_timespans = (
            ("day", 24 * 60 * 60),
            ("week", 7 * 24 * 60 * 60),
            ("month", 30 * 24 * 60 * 60),
            ("half_year", 180 * 24 * 60 * 60),
            ("all_time", 1 << 32),
        )
        now = datetime.now().timestamp()
        guild_statistics: dict[int, Timespans] = defaultdict(_timespan_factory)
        global_statistics = _timespan_factory()

        event: EventType
        spanname: typing.Literal["day", "week", "month", "half_year", "all_time"]
        period: typing.Literal["previous", "current"]

        with self.statistics.open("rb") as fd:
            unpacker = msgpack.Unpacker(fd, use_list=False)
            timestamp: int
            for timestamp, event in unpacker:
                increase = self.process_event(event)
                if increase is None:
                    continue
                guild_id = typing.cast(int, event.get("guild_id", event.get("guild")))
                for spanname, period in [  # type: ignore
                    (name, "current" if now - timestamp < cutoff else "previous")
                    for name, cutoff in all_timespans
                    if now - timestamp < cutoff * 2
                ]:
                    for key1, key2 in increase:
                        guild_statistics[guild_id][spanname][key1][key2][period] += 1
                        global_statistics[spanname][key1][key2][period] += 1

        logger.debug(f"processed statistics data in {time.monotonic() - start:.3f}s")
        return guild_statistics, global_statistics

    def process_event(
        self, event: AllEventType
    ) -> tuple[
        tuple[
            typing.Literal["punishments", "rules", "traffic", "categories", "services"],
            str,
        ],
        ...,
    ] | None:
        rule: str = event.get(
            "rule", event.get("info", {}).get("rule", "norule")  # type: ignore
        )
        if event["name"] == "antispam" or (
            event["name"] == "delete" and rule.startswith("traffic.")
        ):
            return (
                ("traffic", rule),
                ("categories", "antispam"),
                ("services", "antispam"),
            )

        elif event["name"] == "automod" or (
            event["name"] == "delete" and not rule.startswith("traffic.")
        ):
            category = "other"
            if rule.startswith("phishing."):
                category = "phishing"
            elif rule.startswith("advertisement."):
                category = "advertisement"
            return (
                ("rules", rule),
                ("categories", category),
                ("services", "automod"),
            )

        elif event["name"] == "punishment" or event["name"] == "challenge":
            return (("punishments", event["action"].split("-")[0]),)

        elif event["name"] in (
            "slowmode",
            "antiraid",
            "joinguard",
            "super_verification",
            "name",
            "dehoist",
            "bansync",
            "raid",
            "linkfilter",
        ):
            return (("services", event["name"]),)

        elif event["name"] == "nickname":
            return (("services", "dehoist"),)

        logger.debug(f"unknown statistics event: {event}")
        return None

    def on_unload(self) -> None:
        self.save_data()


class Event(typing.NamedTuple):
    time: int
    event: EventType


class Timespans(typing.TypedDict):
    day: Statistics
    week: Statistics
    month: Statistics
    half_year: Statistics
    all_time: Statistics


class Statistics(typing.TypedDict):
    punishments: dict[str, Stat]
    rules: dict[str, Stat]
    traffic: dict[str, Stat]
    categories: dict[str, Stat]
    services: dict[str, Stat]


class Stat(typing.TypedDict):
    previous: int
    current: int


def _timespan_factory() -> Timespans:
    return {
        "day": _statistics_factory(),
        "week": _statistics_factory(),
        "month": _statistics_factory(),
        "half_year": _statistics_factory(),
        "all_time": _statistics_factory(),
    }


def _statistics_factory() -> Statistics:
    return {
        "punishments": defaultdict(_stat_factory),
        "rules": defaultdict(_stat_factory),
        "traffic": defaultdict(_stat_factory),
        "categories": defaultdict(_stat_factory),
        "services": defaultdict(_stat_factory),
    }


def _stat_factory() -> Stat:
    return {"previous": 0, "current": 0}
