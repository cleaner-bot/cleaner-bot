from __future__ import annotations

import logging
import typing
from collections import defaultdict

import hikari

from ._types import ConfigType, EntitlementsType, KernelType, SlowmodeTriggeredEvent
from .helpers.settings import get_config
from .helpers.task import complain_if_none, safe_background_call

logger = logging.getLogger(__name__)
EMERGENCY_INCREASE: typing.Final = 100
SLOWMODE: typing.Final[list[int]] = [round(x**1.3 / 15) for x in range(60)]


class SlowmodeService:
    guilds: dict[int, dict[int, SlowmodeChannel]]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.bindings["slowmode"] = self.message_create
        self.kernel.bindings["slowmode:timer"] = self.on_timer

        self.guilds = defaultdict(
            lambda: defaultdict(
                lambda: {
                    "current": None,
                    "message_count": [0, 0, 0, 0, 0, 0],
                    "pending_message_count": 0,
                    "emergency_increased": False,
                }
            )
        )

    async def message_create(
        self,
        message: hikari.Message,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> None:
        assert message.guild_id is not None, "this is impossible"
        channel = self.guilds[message.guild_id][message.channel_id]
        channel["pending_message_count"] += 1

        if (
            channel["pending_message_count"] >= EMERGENCY_INCREASE
            and not channel["emergency_increased"]
            and (channel["current"] is not None and channel["current"] < 10)
        ):
            if channel_ratelimit := complain_if_none(
                self.kernel.bindings.get("http:channel_ratelimit"),
                "http:channel_ratelimit",
            ):
                channel["emergency_increased"] = True
                guildchannel = self.kernel.bot.cache.get_guild_channel(
                    message.channel_id
                )
                if (
                    guildchannel is not None
                    and isinstance(guildchannel, hikari.GuildTextChannel)
                    and guildchannel.rate_limit_per_user.seconds <= 10
                ):
                    if track := complain_if_none(
                        self.kernel.bindings.get("track"), "track"
                    ):
                        info: SlowmodeTriggeredEvent = {
                            "name": "slowmode",
                            "guild_id": message.guild_id,
                            "emergency": True,
                            "rate_limit_per_user": 10,
                        }
                        safe_background_call(track(info))

                    logger.debug(
                        f"emergency slowmode in {message.channel_id}@{message.guild_id}"
                    )
                    safe_background_call(channel_ratelimit(guildchannel, 10))

    async def on_timer(self) -> None:
        for guild_id, channels in self.guilds.items():
            config = await get_config(self.kernel, guild_id)
            if not config["slowmode_enabled"]:
                continue
            exception_channels = set(map(int, config["slowmode_exceptions"]))
            for channel_id, details in channels.items():
                details["message_count"].pop(0)
                details["message_count"].append(details["pending_message_count"])
                details["pending_message_count"] = 0
                details["emergency_increased"] = False

                recommended = self.get_recommendation(
                    0 if channel_id in exception_channels else 1,
                    details["current"],
                    details["message_count"],
                )
                if recommended is None:
                    continue

                details["current"] = recommended

                channel = self.kernel.bot.cache.get_guild_channel(channel_id)
                if (
                    channel is None
                    or not isinstance(channel, hikari.GuildTextChannel)
                    or channel.rate_limit_per_user.seconds == recommended
                    or channel.rate_limit_per_user.seconds > 10
                ):
                    continue

                logger.debug(
                    f"changed slowmode rate_limit_per_user={recommended} "
                    f"channel={channel_id} guild={guild_id}"
                )

                if track := complain_if_none(
                    self.kernel.bindings.get("track"), "track"
                ):
                    info: SlowmodeTriggeredEvent = {
                        "name": "slowmode",
                        "guild_id": guild_id,
                        "emergency": False,
                        "rate_limit_per_user": recommended,
                    }
                    safe_background_call(track(info))

                if channel_ratelimit := complain_if_none(
                    self.kernel.bindings.get("http:channel_ratelimit"),
                    "http:channel_ratelimit",
                ):
                    safe_background_call(channel_ratelimit(channel, recommended))

    def get_recommendation(
        self, default: int, current: int | None, counts: list[int]
    ) -> int | None:
        spike = counts[-1]
        avg = round(sum(counts) / len(counts))

        if default == 0:  # exception channel, decrease slowmode
            spike //= 5
            avg //= 5

        spike_rt = default + (10 if spike >= len(SLOWMODE) else SLOWMODE[spike])
        avg_rt = default + (10 if avg >= len(SLOWMODE) else SLOWMODE[avg])

        if avg_rt != current or spike_rt > current + 1:
            recommendation = (
                spike_rt if current is not None and spike_rt > current + 1 else avg_rt
            )
            return min(10, recommendation)
        return None


class SlowmodeChannel(typing.TypedDict):
    current: int | None
    message_count: list[int]
    pending_message_count: int
    emergency_increased: bool
