import logging

import hikari

from ._types import (
    BanSyncTriggeredEvent,
    ConfigType,
    EntitlementsType,
    KernelType,
    RPCResponse,
)
from .helpers.binding import complain_if_none, safe_call
from .helpers.localization import Message
from .helpers.settings import get_entitlements

logger = logging.getLogger(__name__)


class BanSyncService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.rpc["bansync:import"] = self.import_bans
        self.kernel.bindings["bansync:ban"] = self.ban_member
        self.kernel.bindings["bansync:member:create"] = self.on_member_create
        self.kernel.bindings["bansync:ban:create"] = self.on_ban_create
        self.kernel.bindings["bansync:ban:delete"] = self.on_ban_delete

    async def ban_member(
        self, member: hikari.Member, config: ConfigType, list_id: str
    ) -> None:
        name = await self.kernel.database.hget(f"bansync:banlist:{list_id}", "name")
        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
                info: BanSyncTriggeredEvent = {
                    "name": "bansync",
                    "guild_id": member.guild_id,
                    "list_id": int(list_id),
                }
                await safe_call(track(info), True)

            reason = Message(
                "components_bansync_reason",
                {
                    "banlist": list_id,
                    "name": name.decode() if name is not None else "Unnamed",
                },
            )
            await safe_call(
                challenge(member, config, False, reason, 3),
                True,
            )

    async def on_member_create(
        self, member: hikari.Member, config: ConfigType, entitlements: EntitlementsType
    ) -> bool:
        for list_id in config["bansync_subscribed"]:
            if await self.kernel.database.sismember(
                f"bansync:banlist:{list_id}:users", str(member.id)
            ):
                await self.ban_member(member, config, list_id)
                return True

        return False

    async def on_ban_create(self, event: hikari.BanCreateEvent) -> None:
        entitlements = await get_entitlements(self.kernel.database, event.guild_id)
        banlists = await self.kernel.database.smembers(
            f"guild:{event.guild_id}:bansync:lists"
        )
        for list_id in map(bytes.decode, banlists):
            auto_sync = await self.kernel.database.hget(
                f"bansync:banlist:{list_id}", "auto_sync"
            )
            if auto_sync is None or str(event.guild_id) not in auto_sync.decode().split(
                ","
            ):
                continue
            count = await self.kernel.database.scard(f"bansync:banlist:{list_id}:users")
            if count >= entitlements["bansync_user_limit"]:
                continue
            if await self.kernel.database.sadd(
                f"bansync:banlist:{list_id}:users", (str(event.user.id),)
            ):
                logger.debug(
                    f"added ban of {event.user.id} in {event.guild_id} "
                    f"to banlist {list_id}"
                )

    async def on_ban_delete(self, event: hikari.BanDeleteEvent) -> None:
        banlists = await self.kernel.database.smembers(
            f"guild:{event.guild_id}:bansync:lists"
        )
        for list_id in map(bytes.decode, banlists):
            auto_sync = await self.kernel.database.hget(
                f"bansync:banlist:{list_id}", "auto_sync"
            )
            if auto_sync is None or str(event.guild_id) not in auto_sync.decode().split(
                ","
            ):
                continue
            if await self.kernel.database.srem(
                f"bansync:banlist:{list_id}:users", (str(event.user.id),)
            ):
                logger.debug(
                    f"removed ban of {event.user.id} in {event.guild_id} "
                    f"to banlist {list_id}"
                )

    async def import_bans(self, guild_id: int, banlist_id: int) -> RPCResponse:
        logger.info(f"importing bans of {guild_id} into {banlist_id}")
        guild = self.kernel.bot.cache.get_guild(guild_id)
        if guild is None:
            logger.debug(f"tried to import bans for {guild_id=}, but not found")
            return {"ok": False, "data": None, "message": "Guild not found"}

        myself = guild.get_my_member()
        if myself is None:
            logger.debug(f"tried to import bans for {guild_id=}, but myself not found")
            return {"ok": False, "data": None, "message": "Bot not in cache"}

        for role in myself.get_roles():
            if role.permissions & (
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.BAN_MEMBERS
            ):
                break
        else:
            return {
                "ok": False,
                "data": None,
                "message": "Missing ban members permission",
            }

        entitlements = await get_entitlements(self.kernel.database, guild_id)
        current_length = await self.kernel.database.scard(
            f"bansync:banlist:{banlist_id}:users"
        )
        if current_length >= entitlements["bansync_user_limit"]:
            return {"ok": False, "data": None, "message": "Reached user limit of list"}

        total_added = 0
        async for users in self.kernel.bot.rest.fetch_bans(guild).chunk(1_000):
            added = await self.kernel.database.sadd(
                f"bansync:banlist:{banlist_id}:users",
                [str(ban.user.id) for ban in users],
            )
            total_added += added
            if current_length + total_added >= entitlements["bansync_user_limit"]:
                break

        return {"ok": True, "data": total_added, "message": "OK"}
