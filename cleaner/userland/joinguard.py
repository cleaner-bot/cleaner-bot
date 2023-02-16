import logging

import hikari
from expirepy import ExpiringSet

from ._types import (
    ConfigType,
    EntitlementsType,
    JoinGuardTriggeredEvent,
    KernelType,
    RPCResponse,
)
from .helpers.localization import Message
from .helpers.settings import get_config, get_entitlements
from .helpers.task import complain_if_none, safe_background_call

logger = logging.getLogger(__name__)


class JoinGuardService:
    whitelisted: ExpiringSet[str]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["joinguard"] = self.member_create
        self.kernel.rpc["joinguard"] = self.on_joinguard

        self.whitelisted = ExpiringSet(expires=30)

    async def member_create(
        self, member: hikari.Member, config: ConfigType, entitlements: EntitlementsType
    ) -> bool:
        bound_member_id = f"{member.guild_id}-{member.id}"
        if bound_member_id in self.whitelisted:
            return False

        logger.debug(f"user tried to join (user={member.id} guild={member.guild_id})")

        if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
            info: JoinGuardTriggeredEvent = {
                "name": "joinguard",
                "guild_id": member.guild_id,
            }
            await safe_background_call(track(info))

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            await safe_background_call(
                challenge(member, config, False, Message("log_joinguard_bypass"), 2)
            )

        return True

    async def on_joinguard(
        self, guild_id: int, user_id: int, token: str
    ) -> RPCResponse:
        guild = self.kernel.bot.cache.get_guild(guild_id)
        if guild is None:
            logger.debug(f"{user_id} tried to join a not foun ")
            return {"ok": False, "message": "Guild not found", "data": None}

        config = await get_config(self.kernel, guild.id)
        entitlements = await get_entitlements(self.kernel, guild.id)

        if not config["joinguard_enabled"]:
            return {"ok": False, "message": "joinguard is not enabled", "data": None}

        if entitlements["plan"] < entitlements["joinguard"]:
            return {
                "ok": False,
                "message": "not entitled to use joinguard",
                "data": None,
            }

        nickname: hikari.UndefinedOr[str] = hikari.UNDEFINED
        if config["name_dehoisting_enabled"]:
            user = self.kernel.bot.cache.get_user(user_id)
            if user is None:
                user = await self.kernel.bot.rest.fetch_user(user_id)

            name = user.username.lstrip("! ")
            if not name:
                name = "dehoisted"

            if name != user.username:
                nickname = name

        me = guild.get_my_member()
        if me is not None:
            permissions = hikari.Permissions(0)
            for role in me.get_roles():
                permissions |= role.permissions

            if permissions & hikari.Permissions.ADMINISTRATOR > 0:
                pass
            elif permissions & hikari.Permissions.CREATE_INSTANT_INVITE == 0:
                return {
                    "ok": False,
                    "message": "no permissions to invite",
                    "data": None,
                }
            elif permissions & hikari.Permissions.CHANGE_NICKNAME == 0:
                nickname = hikari.UNDEFINED

        self.whitelisted.add(f"{guild.id}-{user_id}")
        try:
            await self.kernel.bot.rest.add_user_to_guild(
                token, guild, user_id, nickname=nickname
            )
        except hikari.ForbiddenError:
            logger.debug(f"banned {user_id} tried to join {guild.id}")
            await self.kernel.database.set(
                f"guild:{guild_id}:joinguard:{user_id}", "You are banned", ex=300
            )
            return {"ok": False, "message": "You are banned", "data": None}

        logger.debug(f"user {user_id} joined {guild.id}")
        return {"ok": True, "message": "OK", "data": None}
