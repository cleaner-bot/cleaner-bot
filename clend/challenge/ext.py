import asyncio
import hashlib
import json
import logging
import typing

import hikari
from hikari.internal.time import utc_datetime
import msgpack  # type: ignore

from cleaner_conf.guild import GuildConfig, GuildEntitlements
from cleaner_i18n.translate import translate

from ..bot import TheCleaner
from ..shared.button import add_link
from ..shared.channel_perms import permissions_for
from ..shared.protect import protect, protected_call
from ..shared.sub import listen as pubsub_listen, Message
from ..shared.risk import calculate_risk_score


logger = logging.getLogger(__name__)
REQUIRED_TO_SEND = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES


def get_min_risk(config: GuildConfig, entitlements: GuildEntitlements) -> float | None:
    level = config.challenge_interactive_level
    if level < 2 and entitlements.challenge_interactive_join_risk < entitlements.plan:
        level = 2

    if level == 0:
        return config.challenge_interactive_joinrisk_custom
    return [None, 1, 0.7, 0.3, 0][level - 1]


class ChallengeExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.MemberCreateEvent, self.on_member_create),
            (hikari.MemberUpdateEvent, self.on_member_update),
            (hikari.InteractionCreateEvent, self.on_interaction_create),
        ]
        self.task = None

    def on_load(self):
        self.task = asyncio.create_task(protect(self.verifyd))

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def on_member_create(self, event: hikari.MemberCreateEvent):
        if event.user.is_bot or event.member.is_pending is True:
            return
        await self.member_joined(event.member)

    async def on_member_update(self, event: hikari.MemberUpdateEvent):
        old_member = event.old_member
        if (
            event.user.is_bot
            or event.member.is_pending is not False
            or (old_member is not None and old_member.is_pending is False)
        ):
            return
        await self.member_joined(event.member)

    async def member_joined(self, member: hikari.Member):
        config = self.get_config(member.guild_id)
        entitlements = self.get_entitlements(member.guild_id)
        if config is None or entitlements is None:
            logging.warning(f"uncached guild settings: {member.guild_id}")
            return

        if (
            not config.challenge_interactive_enabled
            or not config.challenge_interactive_take_role
        ):
            return

        min_risk = get_min_risk(config, entitlements)
        if min_risk is None:  # its off
            return

        actual_risk = calculate_risk_score(member.user)
        if actual_risk < min_risk:
            return

        guild = member.get_guild()
        if guild is None:
            return  # this should never happen

        role = guild.get_role(int(config.challenge_interactive_role))
        if (
            role is None
            or role.is_managed
            or role.position == 0
            or role in member.role_ids
        ):
            return

        me = guild.get_my_member()
        if me is None:
            return

        top_role = me.get_top_role()
        if top_role is not None and role.position >= top_role.position:
            return

        for my_role in me.get_roles():
            if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            return

        await member.add_role(role)

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent):
        interaction = event.interaction
        if not isinstance(interaction, hikari.ComponentInteraction):
            return
        elif not interaction.custom_id.startswith("challenge"):
            return

        age = (utc_datetime() - interaction.created_at).total_seconds()
        if age > 3:
            logger.error(f"received interaction that is older than 3s ({age:.3f}s)")
        elif age > 1:
            logger.warning(f"received interaction that is older than 1s ({age:.3f}s)")
        else:
            logger.debug(f"got interaction with age {age:.3f}s")

        try:
            await self.create_flow(interaction)
        except Exception as e:
            logger.exception("Error occured during component interaction", exc_info=e)
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=translate(interaction.locale, "challenge_internal_error"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

    async def create_flow(self, interaction: hikari.ComponentInteraction):
        database = self.bot.database
        guild = interaction.get_guild()
        if guild is None:
            return

        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"challenge_{s}", **k
        )
        config = self.get_config(guild.id)
        entitlements = self.get_entitlements(guild.id)
        if config is None or entitlements is None:
            logger.warning(f"uncached guild settings: {guild.id}")
            component = self.bot.bot.rest.build_action_row()
            add_link(component, t("discord"), "https://cleaner.leodev.xyz/discord")

            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("no_settings"),
                component=component,
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        challenge_interactive_role = int(config.challenge_interactive_role)
        if not config.challenge_interactive_enabled:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("disabled"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif not challenge_interactive_role:
            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("no_role", action=act),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        member = interaction.member
        if member is None or (
            (challenge_interactive_role not in member.role_ids)
            == config.challenge_interactive_take_role
        ):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("already_verified"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        forced_challenge = await database.exists(
            f"guild:{guild.id}:user:{member.id}:challenge"
        )
        challenge = True

        if not forced_challenge:
            min_risk = get_min_risk(config, entitlements)
            actual_risk = calculate_risk_score(member.user)
            challenge = min_risk is not None and actual_risk >= min_risk

        role = guild.get_role(challenge_interactive_role)
        if role is None:
            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("role_gone", action=act),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif role.is_managed:
            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("role_managed", action=act, role=role.id),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif role.position == 0:
            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("role_everyone", action=act),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        me = guild.get_my_member()
        if me is None:
            component = self.bot.bot.rest.build_action_row()
            add_link(component, "Support", "https://cleaner.leodev.xyz/discord")

            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("no_myself"),
                component=component,
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        top_role = me.get_top_role()
        if top_role is not None and role.position >= top_role.position:
            component = self.bot.bot.rest.build_action_row()
            add_link(
                component,
                t("hierarchy_link"),
                "https://cleaner.leodev.xyz/help/hierarchy",
            )

            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("hierarchy", action=act, role=role.id),
                component=component,
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        for my_role in me.get_roles():
            if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("no_perms", action=act),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        if challenge:
            flow = hashlib.sha256(interaction.id.to_bytes(8, "big")).hexdigest()
            logger.debug(
                f"created flow for {interaction.user.id}@{interaction.guild_id}: {flow}"
            )

            await self.bot.database.set(
                f"challenge:flow:{flow}:user", interaction.user.id, ex=300
            )
            await self.bot.database.set(
                f"challenge:flow:{flow}:guild", interaction.guild_id, ex=300
            )

            component = self.bot.bot.rest.build_action_row()
            url = f"https://cleaner.leodev.xyz/challenge?flow={flow}"
            add_link(component, t("link"), url)

            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("content"),
                component=component,
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        else:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("verified"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

            if config.challenge_interactive_take_role:
                await member.remove_role(role)
            else:
                await member.add_role(role)

    async def verifyd(self):
        pubsub = self.bot.database.pubsub()
        await pubsub.subscribe("pubsub:challenge-verify")
        await pubsub.subscribe("pubsub:challenge-send")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, Message):
                continue

            if event.channel == b"pubsub:challenge-verify":
                flow = event.data.decode()
                asyncio.create_task(protected_call(self.verify_flow(flow)))
            else:
                data = msgpack.unpackb(event.data)
                asyncio.create_task(
                    protected_call(self.send_embed(data["channel"], data["guild"]))
                )

    async def verify_flow(self, flow: str):
        logger.debug(f"flow has been solved: {flow}")

        user_id = await self.bot.database.get(f"challenge:flow:{flow}:user")
        guild_id = await self.bot.database.get(f"challenge:flow:{flow}:guild")

        guild = self.bot.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(f"uncached guild: {guild_id}")
            return
        config = self.get_config(guild.id)

        if config is None:
            logger.warning(f"uncached guild settings: {guild_id}")
            return

        role = guild.get_role(int(config.challenge_interactive_role))
        if role is None or role.is_managed or role.position == 0:
            return

        me = guild.get_my_member()
        if me is None:
            return

        top_role = me.get_top_role()
        if top_role is not None and role.position >= top_role.position:
            return

        for my_role in me.get_roles():
            if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            return

        routine = self.bot.bot.rest.add_role_to_member
        if config.challenge_interactive_take_role:
            routine = self.bot.bot.rest.remove_role_from_member

        await routine(guild.id, int(user_id), role.id)

    async def send_embed(self, channel_id: int, guild_id: int):
        channel = self.bot.bot.cache.get_guild_channel(channel_id)
        if channel is None or not isinstance(channel, hikari.TextableGuildChannel):
            return

        if channel.guild_id != guild_id:
            return

        guild = self.bot.bot.cache.get_guild(guild_id)
        if guild is None:
            logger.warning(f"uncached guild: {guild_id}")
            return

        config = self.get_config(guild_id)
        if config is None:
            logger.warning(f"uncached guild settings: {guild_id}")
            return

        me = guild.get_my_member()
        if me is None:
            return

        perms = permissions_for(me, channel)
        if (
            perms & hikari.Permissions.ADMINISTRATOR == 0
            and perms & REQUIRED_TO_SEND != REQUIRED_TO_SEND
        ):
            return

        t = lambda s: translate(  # noqa E731
            guild.preferred_locale, f"challenge_embed_{s}"
        )
        component = self.bot.bot.rest.build_action_row()
        (
            component.add_button(hikari.ButtonStyle.PRIMARY, "challenge")
            .set_label(t("verify"))
            .add_to_container()
        )
        add_link(component, t("privacy"), "https://cleaner.leodev.xyz/legal/privacy")

        embed = hikari.Embed(
            title=t("title"),
            description=t("description"),
            color=0x0284C7
        )
        await channel.send(embed=embed, component=component)

    def get_config(self, guild_id: int) -> GuildConfig | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_config(guild_id)

    def get_entitlements(self, guild_id: int) -> GuildEntitlements | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_entitlements(guild_id)
