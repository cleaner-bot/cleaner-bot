import logging

import hikari

from ._types import KernelType, RPCResponse
from .helpers.binding import complain_if_none, safe_call
from .helpers.escape import escape_markdown
from .helpers.localization import Message
from .helpers.permissions import DANGEROUS_PERMISSIONS
from .helpers.settings import get_config

logger = logging.getLogger(__name__)


class SuperVerificationService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.rpc["super-verification"] = self.rpc_verify

    async def rpc_verify(self, guild_id: int, user_id: int) -> RPCResponse:
        deleted = await self.kernel.database.hdel(
            f"guild:{guild_id}:timelimit", (str(user_id),)
        )
        if not deleted:
            return {"ok": False, "message": "already verified", "data": None}

        guild = self.kernel.bot.cache.get_guild(int(guild_id))
        if guild is None or (me := guild.get_my_member()) is None:
            return {"ok": False, "message": "guild not found", "data": None}

        config = await get_config(self.kernel, guild_id)

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
