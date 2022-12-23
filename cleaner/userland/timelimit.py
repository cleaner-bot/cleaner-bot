import logging
from datetime import datetime, timedelta

import hikari
from hikari.internal.time import utc_datetime

from ._types import KernelType, TimeLimitTriggeredEvent
from .helpers.binding import complain_if_none, safe_call
from .helpers.duration import duration_to_text
from .helpers.localization import Message
from .helpers.settings import get_config

logger = logging.getLogger(__name__)


class TimeLimitService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["timelimit:create"] = self.member_create
        self.kernel.bindings["timelimit:delete"] = self.member_delete
        self.kernel.bindings["timelimit:timer"] = self.on_timer

    async def member_create(self, member: hikari.Member) -> None:
        await self.kernel.database.hset(
            f"guild:{member.guild_id}:timelimit",
            {str(member.id): member.joined_at.isoformat()},
        )

    async def member_delete(
        self, guild_id: hikari.Snowflake, user_id: hikari.Snowflake
    ) -> None:
        await self.kernel.database.hdel(f"guild:{guild_id}:timelimit", (str(user_id),))

    async def on_timer(self) -> None:
        now = utc_datetime()
        for guild in self.kernel.bot.cache.get_guilds_view().values():
            config = await get_config(self.kernel, guild.id)
            if not config["verification_timelimit_enabled"]:
                continue
            cutoff_time = now - timedelta(seconds=config["verification_timelimit"])

            members = await self.kernel.database.hgetall(f"guild:{guild.id}:timelimit")
            members_to_kick = set(
                member_id
                for member_id, join in members.items()
                if datetime.fromisoformat(join.decode()) <= cutoff_time
            )
            if not members_to_kick:
                continue

            await self.kernel.database.hdel(
                f"guild:{guild.id}:timelimit", members_to_kick
            )
            for member_id in map(int, members_to_kick):
                member = guild.get_member(member_id)
                if member is None:
                    logger.debug(
                        f"ignoring verification timelimit for {member_id=}"
                        f" {guild.id=} because not cached"
                    )
                    continue

                roles = list(member.role_ids)
                if (
                    config["verification_enabled"]
                    and config["verification_take_role"]
                    and (
                        (role_id := hikari.Snowflake(config["verification_role"]))
                        in roles
                    )
                ):
                    roles.remove(role_id)
                
                if guild.id in roles:
                    roles.remove(guild.id)

                if roles:  # verified somehow
                    logger.debug(
                        f"ignoring verification timelimit for {member_id=}"
                        f" {guild.id=} because already verified: {roles}"
                    )
                    continue

                if track := complain_if_none(
                    self.kernel.bindings.get("track"), "track"
                ):
                    info: TimeLimitTriggeredEvent = {
                        "name": "timelimit",
                        "guild_id": guild.id,
                    }
                    await safe_call(track(info), True)

                logger.debug(f"verification timelimit for {member_id} in {guild.id}")
                if challenge := complain_if_none(
                    self.kernel.bindings.get("http:challenge"),
                    "http:challenge",
                ):
                    reason = Message(
                        "log_verification_timelimit",
                        {
                            "timelimit": duration_to_text(
                                config["verification_timelimit"]
                            )
                        },
                    )

                    await safe_call(challenge(member, config, False, reason, 2), True)
