import asyncio
import typing
import logging
import json

import hikari

from ..bot import TheCleaner
from ..shared.channel_perms import permissions_for
from ..shared.protect import protected_call


logger = logging.getLogger(__name__)


class SyncExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
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
        for guild in self.bot.bot.cache.get_guilds_view().values():
            asyncio.create_task(protected_call(self.new_guild(guild)))

    async def on_new_guild(
        self, event: hikari.GuildJoinEvent | hikari.GuildAvailableEvent
    ):
        guild = event.get_guild()
        if guild is not None:
            await self.new_guild(guild)

    async def new_guild(self, guild: hikari.GatewayGuild):
        database = self.bot.database
        await database.set(f"guild:{guild.id}:sync:added", "1")
        await self.sync_myself(guild)
        await self.sync_roles(guild)
        await self.sync_channels(guild)

    async def on_destroy_guild(self, event: hikari.GuildLeaveEvent):
        database = self.bot.database
        await database.delete(
            *(
                f"guild:{event.guild_id}:sync:{x}"
                for x in ("added", "myself", "roles", "channels")
            )
        )

    async def on_update_role(self, event: hikari.RoleEvent):
        # TODO: add role.get_guild() to hikari
        guild = self.bot.bot.cache.get_guild(event.guild_id)
        if guild is not None:
            await self.sync_roles(guild)
            await self.sync_channels(guild)
            await self.sync_myself(guild)

    async def on_update_channel(self, event: hikari.GuildChannelEvent):
        guild = event.get_guild()
        if guild is not None:
            await self.sync_channels(guild)

    async def on_member_update(self, event: hikari.MemberUpdateEvent):
        me = self.bot.bot.get_me()
        if me is None or event.user_id != me.id:
            return
        guild = event.get_guild()
        if guild is not None:
            await self.sync_myself(guild)

    async def sync_myself(self, guild: hikari.GatewayGuild):
        perms = hikari.Permissions.NONE
        me = guild.get_my_member()
        if me is not None:
            for role in me.get_roles():
                perms |= role.permissions

        data = {"permissions": {k.name: True for k in perms}}

        database = self.bot.database
        await database.set(f"guild:{guild.id}:sync:myself", json.dumps(data))

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
                and top_role_position > role.position > 0,
                "is_managed": role.is_managed or role.position == 0,
            }
            for role in guild.get_roles().values()
        ]

        database = self.bot.database
        await database.set(f"guild:{guild.id}:sync:roles", json.dumps(data))

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

        database = self.bot.database
        await database.set(f"guild:{guild.id}:sync:channels", json.dumps(data))
