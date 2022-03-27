import asyncio
import logging
import typing

import hikari
import msgpack  # type: ignore

from cleaner_conf.guild import GuildEntitlements

from ..bot import TheCleaner


logger = logging.getLogger(__name__)


class AnalyticsExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_guild_join),
            (hikari.GuildLeaveEvent, self.on_guild_leave),
            (hikari.MemberChunkEvent, self.on_member_chunk),
        ]

    def on_load(self):
        for guild in self.bot.bot.cache.get_guilds_view().values():
            if guild.id in self.bot.guild_has_members_cached:
                asyncio.create_task(self.check_guild(guild))

    async def on_guild_join(self, event: hikari.GuildJoinEvent):
        channel = self.get_channel()
        if channel is None:
            return

        embed = (
            hikari.Embed(color=0x34D399)
            .set_author(name="Joined guild!")
            .set_thumbnail(event.guild.make_icon_url())
            .add_field(name="Name", value=event.guild.name)
            .add_field(name="Members", value=str(event.guild.member_count))
            .add_field(name="Features", value=", ".join(map(str, event.guild.features)))
            .set_footer(str(event.guild_id))
        )
        if event.guild.vanity_url_code:
            vanity = event.guild.vanity_url_code
            embed.add_field("Vanity Invite", f"https://discord.gg/{vanity}")
        await channel.send(embed=embed)

    async def on_guild_leave(self, event: hikari.GuildLeaveEvent):
        channel = self.get_channel()
        if channel is None:
            return

        embed = (
            hikari.Embed(color=0xF87171)
            .set_author(name="Left guild!")
            .set_footer(str(event.guild_id))
        )
        if event.old_guild is not None:
            embed.set_thumbnail(event.old_guild.make_icon_url())
            embed.add_field(name="Name", value=event.old_guild.name)
            embed.add_field(name="Members", value=str(event.old_guild.member_count))
            embed.add_field(
                name="Features", value=", ".join(map(str, event.old_guild.features))
            )
            if event.old_guild.vanity_url_code:
                vanity = event.old_guild.vanity_url_code
                embed.add_field("Vanity Invite", f"https://discord.gg/{vanity}")
        await channel.send(embed=embed)

    async def on_member_chunk(self, event: hikari.MemberChunkEvent):
        if event.chunk_index != event.chunk_count - 1:
            return  # guild is not fully chunked yet

        self.bot.guild_has_members_cached.add(event.guild_id)

        guild = self.bot.bot.cache.get_guild(event.guild_id)
        if guild is not None:
            await self.check_guild(guild)

    async def check_guild(self, guild: hikari.GatewayGuild):
        humans = bots = 0
        for member in guild.get_members().values():
            if member.is_bot:
                bots += 1
            else:
                humans += 1

        if humans + bots >= 80 and bots > 2 * humans:
            logger.info(
                f"detected botfarm on guild {guild.name!r} ({guild.id}): "
                f"{humans}:{bots}"
            )
            await self.suspend(guild, f"Bot farm (h={humans}, b={bots})")

    async def suspend(self, guild: hikari.GatewayGuild, reason: str):
        database = self.bot.database
        entitlements = self.get_entitlements(guild.id)
        if entitlements is None:
            return
        elif entitlements.suspended:
            return

        await database.hset(
            f"guild:{guild.id}:entitlements", {"suspended": msgpack.packb(True)}
        )
        entitlements.suspended = True

        channel = self.get_channel()
        if channel is None:
            return

        embed = (
            hikari.Embed(color=0xF87171, description=reason)
            .set_author(name="Suspended guild!")
            .set_thumbnail(guild.make_icon_url())
            .add_field(name="Name", value=guild.name)
            .add_field(name="Members", value=str(guild.member_count))
            .add_field(name="Features", value=str(guild.features))
            .set_footer(str(guild.id))
        )
        if guild.vanity_url_code:
            vanity = guild.vanity_url_code
            embed.add_field("Vanity Invite", f"https://discord.gg/{vanity}")
        await channel.send(embed=embed)

    def get_channel(self) -> hikari.TextableGuildChannel | None:
        guild_id = 905525342385602591
        channel_id = 909832103556964442

        guild = self.bot.bot.cache.get_guild(guild_id)
        if guild is None:
            return None
        return guild.get_channel(channel_id)  # type: ignore

    def get_entitlements(self, guild_id: int) -> GuildEntitlements | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_entitlements(guild_id)
