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
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, app: TheCleanerApp):
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
        ]
        self.task = None

    def on_load(self):
        asyncio.create_task(protected_call(self.loader()))

    async def loader(self):
        for guild in tuple(self.app.bot.cache.get_guilds_view().values()):
            await self.new_guild(guild)
        logger.info("initial sync done")

    async def on_new_guild(
        self, event: hikari.GuildJoinEvent | hikari.GuildAvailableEvent
    ):
        guild = event.get_guild()
        if guild is not None:
            await self.new_guild(guild)

    async def new_guild(self, guild: hikari.GatewayGuild):
        database = self.app.database
        await database.hset(f"guild:{guild.id}:sync", {"added": 1})
        await self.sync_myself(guild)
        await self.sync_roles(guild)
        await self.sync_channels(guild)

    async def on_destroy_guild(self, event: hikari.GuildLeaveEvent):
        database = self.app.database
        await database.delete((f"guild:{event.guild_id}:sync",))

    async def on_update_role(self, event: hikari.RoleEvent):
        # TODO: add role.get_guild() to hikari
        guild = self.app.bot.cache.get_guild(event.guild_id)
        if guild is not None:
            await self.sync_roles(guild)
            await self.sync_channels(guild)
            await self.sync_myself(guild)

    async def on_update_channel(self, event: hikari.GuildChannelEvent):
        guild = event.get_guild()
        if guild is not None:
            await self.sync_channels(guild)

    async def on_member_update(self, event: hikari.MemberUpdateEvent):
        me = self.app.bot.get_me()
        if me is None or event.user_id != me.id:
            return
        guild = event.get_guild()
        if guild is not None:
            await self.sync_myself(guild)
            await self.sync_roles(guild)
            await self.sync_channels(guild)

    async def sync_myself(self, guild: hikari.GatewayGuild):
        perms = hikari.Permissions.NONE
        me = guild.get_my_member()
        if me is not None:
            for role in me.get_roles():
                perms |= role.permissions

        data = {"permissions": {k.name: True for k in perms}}

        database = self.app.database
        await database.hset(f"guild:{guild.id}:sync", {"myself": msgpack.packb(data)})

    async def sync_roles(self, guild: hikari.GatewayGuild):
        me = guild.get_my_member()
        top_role_position = 0
        if me is not None:
            top_role = me.get_top_role()
            if top_role is not None:
                top_role_position = top_role.position

        data = [
            {
                "name": role.name,
                "id": str(role.id),
                "can_control": not role.is_managed
                and top_role_position > role.position > 0
                and role.permissions & DANGEROUS_PERMISSIONS == 0,
                "is_managed": role.is_managed or role.position == 0,
            }
            for role in guild.get_roles().values()
        ]

        database = self.app.database
        await database.hset(f"guild:{guild.id}:sync", {"roles": msgpack.packb(data)})

    async def sync_channels(self, guild: hikari.GatewayGuild):
        me = guild.get_my_member()
        if me is None:
            return

        data = [
            {
                "name": channel.name,
                "id": str(channel.id),
                "permissions": {k.name: True for k in permissions_for(me, channel)},
            }
            for channel in guild.get_channels().values()
            if isinstance(channel, hikari.TextableGuildChannel)
        ]

        database = self.app.database
        await database.hset(f"guild:{guild.id}:sync", {"channels": msgpack.packb(data)})
