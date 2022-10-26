import logging
from datetime import datetime, timedelta

import hikari
from hikari.internal.time import utc_datetime

from ._types import KernelType, RPCResponse, SuperVerificationTriggeredEvent
from .helpers.binding import complain_if_none, safe_call
from .helpers.escape import escape_markdown
from .helpers.localization import Message
from .helpers.permissions import DANGEROUS_PERMISSIONS
from .helpers.settings import get_config

logger = logging.getLogger(__name__)


class SuperVerificationService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["super-verification:create"] = self.member_create
        self.kernel.bindings["super-verification:delete"] = self.member_delete
        self.kernel.bindings["super-verification:timer"] = self.on_timer
        self.kernel.rpc["super-verification"] = self.rpc_verify

    async def member_create(self, member: hikari.Member) -> None:
        await self.kernel.database.hset(
            f"guild:{member.guild_id}:super-verification",
            {str(member.id): member.joined_at.isoformat()},
        )

    async def member_delete(
        self, guild_id: hikari.Snowflake, user_id: hikari.Snowflake
    ) -> None:
        await self.kernel.database.hdel(
            f"guild:{guild_id}:super-verification", (str(user_id),)
        )

    async def on_timer(self) -> None:
        cutoff_time = utc_datetime() - timedelta(minutes=8)
        for guild in self.kernel.bot.cache.get_guilds_view().values():
            config = await get_config(self.kernel.database, guild.id)
            if not config["super_verification_enabled"]:
                continue

            members = await self.kernel.database.hgetall(
                f"guild:{guild.id}:super-verification"
            )
            members_to_kick = set(
                member_id
                for member_id, join in members.items()
                if datetime.fromisoformat(join.decode()) <= cutoff_time
            )
            if not members_to_kick:
                continue

            await self.kernel.database.hdel(
                f"guild:{guild.id}:super-verification", members_to_kick
            )
            for member_id in map(int, members_to_kick):
                member = guild.get_member(member_id)
                if member is None:
                    logger.debug(
                        f"ignoring verification timeout for {member_id=}"
                        f" {guild.id=} because not in cached"
                    )
                    continue

                if track := complain_if_none(
                    self.kernel.bindings.get("track"), "track"
                ):
                    info: SuperVerificationTriggeredEvent = {
                        "name": "super_verification",
                        "guild_id": guild.id,
                    }
                    await safe_call(track(info), True)

                logger.debug(f"verification timeout for {member_id} in {guild.id}")
                if challenge := complain_if_none(
                    self.kernel.bindings.get("http:challenge"),
                    "http:challenge",
                ):
                    reason = Message(
                        "log_superverification_timeout",
                        {"user": member_id, "name": escape_markdown(str(member.user))},
                    )

                    await safe_call(challenge(member, config, False, reason, 2), True)

    async def rpc_verify(self, guild_id: int, user_id: int) -> RPCResponse:
        deleted = await self.kernel.database.hdel(
            f"guild:{guild_id}:super-verification", (str(user_id),)
        )
        if not deleted:
            return {"ok": False, "message": "already verified", "data": None}

        guild = self.kernel.bot.cache.get_guild(int(guild_id))
        if guild is None or (me := guild.get_my_member()) is None:
            return {"ok": False, "message": "guild not found", "data": None}

        config = await get_config(self.kernel.database, guild_id)

        if not config["super_verification_enabled"]:
            return {
                "ok": False,
                "message": "super verification is not enabled",
                "data": None,
            }

        role = guild.get_role(int(config["super_verification_role"]))
        if (
            role is None
            or role.is_managed
            or role.position == 0
            or role.permissions & DANGEROUS_PERMISSIONS
        ):
            return {
                "ok": False,
                "message": "cant or wont give role",
                "data": None,
            }

        top_role = me.get_top_role()
        if top_role is not None and role.position >= top_role.position:
            return {
                "ok": False,
                "message": "role too high",
                "data": None,
            }

        for my_role in me.get_roles():
            if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            return {
                "ok": False,
                "message": "no perms to give role",
                "data": None,
            }

        await self.kernel.bot.rest.add_role_to_member(guild.id, user_id, role.id)

        if config["logging_enabled"]:
            user = self.kernel.bot.cache.get_user(user_id)
            if user is None:
                user = await self.kernel.bot.rest.fetch_user(user_id)

            if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
                message = Message(
                    "log_verified",
                    {"user": str(user.id), "name": escape_markdown(str(user))},
                )
                await safe_call(log(guild_id, message, None, None), True)

        return {"ok": True, "message": "OK", "data": None}
