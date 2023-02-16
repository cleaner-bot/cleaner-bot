import logging
import typing
from collections import defaultdict

import hikari
from expirepy import ExpiringSet

from ._types import AntiRaidTriggeredEvent, ConfigType, EntitlementsType, KernelType
from .helpers.localization import Message
from .helpers.task import complain_if_none, safe_background_call

logger = logging.getLogger(__name__)
DAY: typing.Final = 24 * 3600
MODE_TIMESPANS = (DAY, 3 * DAY, 7 * DAY)


class AntiRaidService:
    member_joins: dict[int, ExpiringSet[hikari.Snowflake]]
    member_kicks: ExpiringSet[str]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["antiraid"] = self.member_create

        self.member_joins = defaultdict(lambda: ExpiringSet(expires=300))
        self.member_kicks = ExpiringSet(expires=300)

    async def member_create(
        self, member: hikari.Member, config: ConfigType, entitlements: EntitlementsType
    ) -> bool:
        bound_member_id = f"{member.guild_id}-{member.id}"
        limit, time_frame = map(int, config["antiraid_limit"].split("/"))

        member_joins = self.member_joins[member.guild_id]
        member_joins.expires = time_frame
        member_joins.add(member.id)
        if bound_member_id in self.member_kicks:
            self.member_kicks.remove(bound_member_id)

        joiners = member_joins.copy()
        matching = joiners
        if config["antiraid_mode"]:
            timespan = MODE_TIMESPANS[config["antiraid_mode"] - 1]
            matching = set(
                x
                for x in matching
                if abs((x.created_at - member.id.created_at).total_seconds()) < timespan
            )

        if len(matching) <= limit:
            return False

        logger.debug(
            f"antiraid triggered (user={member.id} guild={member.guild_id} "
            f"matching={len(matching)}/{limit})"
        )

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            track = complain_if_none(self.kernel.bindings.get("track"), "track")
            reason = Message(
                "components_antiraid_limit", {"limit": config["antiraid_limit"]}
            )
            for user_id in matching:
                member_to_kick = self.kernel.bot.cache.get_member(
                    member.guild_id, user_id
                )
                if (
                    member_to_kick is not None
                    and f"{member.guild_id}-{user_id}" not in self.member_kicks
                ):
                    await safe_background_call(
                        challenge(member_to_kick, config, False, reason, 1)
                    )

                    if track:
                        info: AntiRaidTriggeredEvent = {
                            "name": "antiraid",
                            "guild_id": member.guild_id,
                            "limit": config["antiraid_limit"],
                            "id": member_to_kick.id,
                        }
                        await safe_background_call(track(info))

        return True
