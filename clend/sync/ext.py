import asyncio
import logging
import typing

import hikari
import msgpack  # type: ignore

from ..app import TheCleanerApp
from ..shared.channel_perms import permissions_for
from ..shared.dangerous import DANGEROUS_PERMISSIONS
from ..shared.protect import protected_call

logger = logging.getLogger(__name__)


class SyncExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_new_guild),
            (hikari.GuildAvailableEvent, self.on_new_guild),
            (hikari.GuildLeaveEvent, self.on_destroy_guild),
            (hikari.RoleCreateEvent, self.on_update_role),
            (hikari.RoleUpdateEvent, self.on_update_role),
            (hikari.RoleDeleteEvent, self.on_update_role),
            (hikari.GuildChannelCreateEvent, self.on_update_channel),
            (hikari.GuildChannelUpdateEvent, self.on_update_channel),
            (hikari.GuildChannelDeleteEvent, self.on_update_channel),
            (hikari.MemberUpdateEvent, self.on_member_update),
            (hikari.GuildUpdateEvent, self.on_guild_update),
        ]
        self.task = None

    def on_load(self) -> None:
        asyncio.create_task(protected_call(self.loader()))

    async def loader(self) -> None:
        for guild in tuple(self.app.bot.cache.get_guilds_view().values()):
            await self.new_guild(guild)
        logger.info("initial sync done")

    async def on_new_guild(
        self, event: hikari.GuildJoinEvent | hikari.GuildAvailableEvent
    ) -> None:
        guild = event.get_guild()
        if guild is not None:
            await self.new_guild(guild)

    async def new_guild(self, guild: hikari.GatewayGuild) -> None:
        await self.sync(
            guild.id,
            {
                "added": 1,
                "guild": self.sync_guild(guild),
                "myself": self.sync_myself(guild),
                "roles": self.sync_roles(guild),
                "channels": self.sync_channels(guild),
            },
        )

    async def on_destroy_guild(self, event: hikari.GuildLeaveEvent) -> None:
        database = self.app.database
        await database.delete((f"guild:{event.guild_id}:sync",))

    async def on_update_role(self, event: hikari.RoleEvent) -> None:
        # TODO: add role.get_guild() to hikari
        guild = self.app.bot.cache.get_guild(event.guild_id)
        if guild is not None:
            await self.sync(
                guild.id,
                {
                    "myself": self.sync_myself(guild),
                    "roles": self.sync_roles(guild),
                    "channels": self.sync_channels(guild),
                },
            )

    async def on_update_channel(self, event: hikari.GuildChannelEvent) -> None:
        guild = event.get_guild()
        if guild is not None:
            await self.sync(
                guild.id,
                {
                    "channels": self.sync_channels(guild),
                },
            )

    async def on_member_update(self, event: hikari.MemberUpdateEvent) -> None:
        me = self.app.bot.get_me()
        if me is None or event.user_id != me.id:
            return
        guild = event.get_guild()
        if guild is not None:
            await self.sync(
                guild.id,
                {
                    "myself": self.sync_myself(guild),
                    "roles": self.sync_roles(guild),
                    "channels": self.sync_channels(guild),
                },
            )

    async def on_guild_update(self, event: hikari.GuildUpdateEvent) -> None:
        await self.sync(
            event.guild_id,
            {
                "guild": self.sync_guild(event.guild),
            },
        )

    def sync_guild(self, guild: hikari.GatewayGuild) -> dict[str, typing.Any]:
        return {"owner_id": guild.owner_id}

    def sync_myself(self, guild: hikari.GatewayGuild) -> dict[str, typing.Any]:
        perms = hikari.Permissions.NONE
        me = guild.get_my_member()
        if me is not None:
            for role in me.get_roles():
                perms |= role.permissions

        return {"permissions": {k.name: True for k in perms}}

    def sync_roles(self, guild: hikari.GatewayGuild) -> list[dict[str, typing.Any]]:
        me = guild.get_my_member()
        top_role_position = 0
        if me is not None:
            top_role = me.get_top_role()
            if top_role is not None:
                top_role_position = top_role.position

        return [
            {
                "name": role.name,
                "id": str(role.id),
                "can_control": (
                    not role.is_managed
                    and top_role_position > role.position > 0
                    and role.permissions & DANGEROUS_PERMISSIONS == 0
                ),
                "is_managed": role.is_managed or role.position == 0,
            }
            for role in guild.get_roles().values()
        ]

    def sync_channels(self, guild: hikari.GatewayGuild) -> list[dict[str, typing.Any]]:
        me = guild.get_my_member()
        if me is None:
            raise RuntimeError("me not found")

        return [
            {
                "name": channel.name,
                "id": str(channel.id),
                "permissions": {k.name: True for k in permissions_for(me, channel)},
            }
            for channel in guild.get_channels().values()
            if isinstance(channel, hikari.TextableGuildChannel)
        ]

    async def sync(self, guild_id: int, data: dict[str, typing.Any]) -> None:
        database = self.app.database
        await database.hset(
            f"guild:{guild_id}:sync",
            {key: msgpack.packb(value) for key, value in data.items()},
        )
