import asyncio
import logging
import typing

import hikari
import msgpack  # type: ignore

from cleaner_conf.guild import GuildEntitlements

from ..bot import TheCleaner
from ..shared.id import time_passed_since


logger = logging.getLogger(__name__)


class AnalyticsExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_guild_join),
            (hikari.GuildLeaveEvent, self.on_guild_leave),
            # (hikari.MemberChunkEvent, self.on_member_chunk),
            (hikari.InteractionCreateEvent, self.on_interaction_create),
        ]

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
            .set_footer(str(event.guild_id))
        )
        owner = self.bot.bot.cache.get_user(event.guild.owner_id)
        if owner is None:
            embed.add_field(name="Owner ID", value=str(event.guild.owner_id))
        else:
            embed.add_field(name="Owner", value=f"{owner} ({owner.id})")
        if event.guild.features:
            embed.add_field(name="Features", value=", ".join(event.guild.features))
        if event.guild.vanity_url_code:
            vanity = event.guild.vanity_url_code
            embed.add_field(name="Vanity Invite", value=f"https://discord.gg/{vanity}")
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

            owner = self.bot.bot.cache.get_user(event.old_guild.owner_id)
            if owner is None:
                embed.add_field(name="Owner ID", value=str(event.old_guild.owner_id))
            else:
                embed.add_field(name="Owner", value=f"{owner} ({owner.id})")

            if event.old_guild.features:
                embed.add_field(
                    name="Features", value=", ".join(event.old_guild.features)
                )

            if event.old_guild.vanity_url_code:
                vanity = event.old_guild.vanity_url_code
                embed.add_field("Vanity Invite", f"https://discord.gg/{vanity}")

        await channel.send(embed=embed)

    async def on_member_chunk(self, event: hikari.MemberChunkEvent):
        # TODO: remove this (guild chunking is disabled!)
        if event.chunk_index != event.chunk_count - 1:
            return  # guild is not fully chunked yet

        self.bot.guild_has_members_cached.add(event.guild_id)

        guild = self.bot.bot.cache.get_guild(event.guild_id)
        if guild is not None:
            await self.acheck_guild(guild)

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent):
        interaction = event.interaction
        if not isinstance(interaction, hikari.ComponentInteraction):
            return
        elif not interaction.custom_id.startswith("suspend/"):
            return
        elif time_passed_since(interaction.id).total_seconds() >= 2.5:
            return

        try:
            parts = interaction.custom_id.split("/")
            message = "wot"
            if parts[1] == "leave":
                try:
                    await self.bot.bot.rest.leave_guild(int(parts[2]))
                except hikari.NotFoundError:
                    message = "not even in it lol"
                else:
                    message = "left"

            elif parts[1] == "remove":
                database = self.bot.database
                entitlements = self.get_entitlements(int(parts[2]))
                await database.hset(
                    f"guild:{parts[2]}:entitlements",
                    {"suspended": msgpack.packb(False)},
                )
                if entitlements is not None and entitlements.suspended:
                    entitlements.suspended = False

                message = "removed the suspension"

            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=message,
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        except Exception as e:
            logger.exception("Error occured during component interaction", exc_info=e)
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content="something went wrong",
                flags=hikari.MessageFlag.EPHEMERAL,
            )

    async def acheck_guild(self, guild: hikari.GatewayGuild):
        loop = asyncio.get_running_loop()
        is_farm, humans, bots = await loop.run_in_executor(
            None, self.check_guild, guild
        )
        if is_farm:
            await self.suspend(guild, f"Bot farm (h={humans}, b={bots})")

    def check_guild(self, guild: hikari.GatewayGuild):
        humans = bots = 0
        members = tuple(guild.get_members().values())  # clone to avoid race conditions
        for member in members:
            if member.is_bot:
                bots += 1
            else:
                humans += 1

        is_farm = humans + bots >= 80 and bots > 2 * humans
        if is_farm:
            logger.info(
                f"detected botfarm on guild {guild.name!r} ({guild.id}): "
                f"{humans}:{bots}"
            )

        return is_farm, humans, bots

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
            .add_field(name="Features", value=", ".join(guild.features))
            .set_footer(str(guild.id))
        )
        if guild.vanity_url_code:
            vanity = guild.vanity_url_code
            embed.add_field("Vanity Invite", f"https://discord.gg/{vanity}")

        component = self.bot.bot.rest.build_action_row()
        (
            component.add_button(
                hikari.ButtonStyle.PRIMARY, f"suspend/leave/{guild.id}"
            )
            .set_label("Leave guild")
            .add_to_container()
        )
        (
            component.add_button(
                hikari.ButtonStyle.DANGER, f"suspend/remove/{guild.id}"
            )
            .set_label("Remove suspension")
            .add_to_container()
        )

        await channel.send(embed=embed, component=component)

    def get_channel(self) -> hikari.TextableGuildChannel | None:
        channel_id = 963043465355206716

        channel = self.bot.bot.cache.get_guild_channel(channel_id)
        return channel  # type: ignore

    def get_entitlements(self, guild_id: int) -> GuildEntitlements | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_entitlements(guild_id)
