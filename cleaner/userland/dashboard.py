import hikari

from ._types import KernelType, RPCResponse
from .helpers.permissions import DANGEROUS_PERMISSIONS, permissions_for


class DashboardService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.rpc["dash:guild-check"] = self.rpc_guild_check
        self.kernel.rpc["dash:guild-info"] = self.rpc_guild_info

    async def rpc_guild_check(self, guilds: tuple[int, ...]) -> RPCResponse:
        return {
            "ok": True,
            "message": "OK",
            "data": [x for x in guilds if self.kernel.bot.cache.get_guild(x)],
        }

    async def rpc_guild_info(self, guild_id: int) -> RPCResponse:
        guild = self.kernel.bot.cache.get_guild(guild_id)
        if guild is None:
            return {"ok": False, "message": "guild_not_found", "data": None}

        me = guild.get_my_member()
        perms = hikari.Permissions.NONE
        top_role_position = 0
        if me is not None:
            for role in me.get_roles():
                perms |= role.permissions
            top_role = me.get_top_role()
            if top_role is not None:
                top_role_position = top_role.position

        data = {
            "id": str(guild_id),
            "name": guild.name,
            "verification_level": guild.verification_level,
            "mfa_level": guild.mfa_level,
            "roles": [
                {
                    "name": role.name,
                    "id": str(role.id),
                    "can_control": (
                        not role.is_managed
                        and top_role_position > role.position > 0
                        and role.permissions & DANGEROUS_PERMISSIONS == 0
                    ),
                    "flags": self.role_flags(role, top_role_position),
                    "is_managed": role.is_managed or role.position == 0,
                    "permissions": {k.name: True for k in role.permissions},
                }
                for role in guild.get_roles().values()
            ],
            "channels": [
                {
                    "name": channel.name,
                    "id": str(channel.id),
                    "type": channel.type,
                    "permissions": (
                        {k.name: True for k in permissions_for(me, channel)}
                        if me is not None
                        else {}
                    ),
                }
                for channel in guild.get_channels().values()
                if isinstance(channel, hikari.TextableGuildChannel)
            ],
            "myself": {"permissions": {k.name: True for k in perms}},
        }
        return {"ok": True, "message": "OK", "data": data}

    def role_flags(self, role: hikari.Role, top_role_position: int) -> list[str]:
        flags = []
        if role.is_managed:
            flags.append("managed")
        if role.position >= top_role_position:
            flags.append("higher_pos")
        if role.position == 0:
            flags.append("everyone")
        if role.permissions & DANGEROUS_PERMISSIONS:
            flags.append("dangerous")
        return flags
