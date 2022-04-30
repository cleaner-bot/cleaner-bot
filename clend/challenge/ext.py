import asyncio
from datetime import datetime
import hashlib
import logging
import typing

import hikari
import msgpack  # type: ignore

from cleaner_conf.guild import GuildConfig, GuildEntitlements
from cleaner_i18n.translate import translate, Message

from ..bot import TheCleaner
from ..shared.button import add_link
from ..shared.channel_perms import permissions_for
from ..shared.event import ILog
from ..shared.protect import protect, protected_call
from ..shared.sub import listen as pubsub_listen, Message as PubMessage
from ..shared.risk import calculate_risk_score
from ..shared.dangerous import DANGEROUS_PERMISSIONS
from ..shared.id import time_passed_since


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
            logger.warning(f"uncached guild settings: {member.guild_id}")
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
        elif (passed := time_passed_since(interaction.id).total_seconds()) >= 2.5:
            return

        logger.debug("used challenge button")

        try:
            try:
                await self.create_flow(interaction)
            except hikari.NotFoundError as e:
                if "Unknown interaction" in str(e):
                    now_passed = time_passed_since(interaction.id).total_seconds()
                    logger.error(
                        f"interaction expired "
                        f"(alleged age={passed:.3f}s, now={now_passed:.3f})"
                    )
                else:
                    raise

        except Exception as e:
            logger.exception("Error occured during component interaction", exc_info=e)
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=translate(interaction.locale, "challenge_internal_error"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        if interaction.custom_id != "challenge":  # old embed
            logger.info(
                f"found old challenge embed {interaction.custom_id} "
                f"in {interaction.guild_id}"
            )
            guild = interaction.get_guild()
            if guild is not None:
                await self.migrate_embed(interaction.message, guild)

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

        act = (
            t("action_take")
            if config.challenge_interactive_take_role
            else t("action_give")
        )

        challenge_interactive_role = int(config.challenge_interactive_role)
        if not config.challenge_interactive_enabled:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("disabled"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif not challenge_interactive_role:
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

        forced_challenge = await database.sismember(
            f"guild:{guild.id}:challenged", member.id
        )
        challenge = True

        if not forced_challenge:
            min_risk = get_min_risk(config, entitlements)
            actual_risk = calculate_risk_score(member.user)
            challenge = min_risk is not None and actual_risk >= min_risk

        role = guild.get_role(challenge_interactive_role)
        if role is None:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("role_gone", action=act),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif role.is_managed:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("role_managed", action=act, role=role.id),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif role.position == 0:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("role_everyone", action=act),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif role.permissions & DANGEROUS_PERMISSIONS:
            component = self.bot.bot.rest.build_action_row()
            add_link(
                component,
                t("role_dangerous_link"),
                "https://cleaner.leodev.xyz/help/role-restrictions"
                "#dangerous-permissions",
            )

            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("role_dangerous", action=act, role=role.id),
                component=component,
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
                "https://cleaner.leodev.xyz/help/role-restrictions#hierarchy",
            )

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

            await self.bot.database.hset(
                f"challenge:flow:{flow}",
                {"user": interaction.user.id, "guild": guild.id},
            )
            await self.bot.database.expire(f"challenge:flow:{flow}", 300)

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

            if config.logging_enabled and config.logging_option_verify:
                log = ILog(
                    guild.id,
                    Message(
                        "components_log_verify_passthrough",
                        {"user": interaction.user.id},
                    ),
                    datetime.utcnow(),
                )
                http = self.bot.extensions.get("clend.http", None)
                if http is None:
                    logger.warning("tried to log http extension is not loaded")
                else:
                    http.queue.sync_q.put(log)

    async def verifyd(self):
        pubsub = self.bot.database.pubsub()
        await pubsub.subscribe("pubsub:challenge-verify")
        await pubsub.subscribe("pubsub:challenge-send")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, PubMessage):
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

        user_id, guild_id = await self.bot.database.hmget(
            f"challenge:flow:{flow}", ("user", "guild")
        )
        if user_id is None or guild_id is None:
            return  # the flow expired, F

        guild = self.bot.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(f"uncached guild: {int(guild_id)}")
            return
        config = self.get_config(guild.id)

        if config is None:
            logger.warning(f"uncached guild settings: {guild.id}")
            return

        role = guild.get_role(int(config.challenge_interactive_role))
        if (
            role is None
            or role.is_managed
            or role.position == 0
            or role.permissions & DANGEROUS_PERMISSIONS
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

        routine = self.bot.bot.rest.add_role_to_member
        if config.challenge_interactive_take_role:
            routine = self.bot.bot.rest.remove_role_from_member

        try:
            await routine(guild.id, int(user_id), role.id)
        except hikari.NotFoundError:
            return  # use left the guild
        finally:
            # delete flow if user left anyway
            await self.bot.database.delete((f"challenge:flow:{flow}",))

        await self.bot.database.srem(f"guild:{guild.id}:challenged", (user_id,))

        if config.logging_enabled and config.logging_option_verify:
            log = ILog(
                guild.id,
                Message("components_log_verify_challenge", {"user": int(user_id)}),
                datetime.utcnow(),
            )
            http = self.bot.extensions.get("clend.http", None)
            if http is None:
                logger.warning("tried to log http extension is not loaded")
            else:
                http.queue.sync_q.put(log)

    def get_message(self, guild: hikari.GatewayGuild) -> dict:
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
            title=t("title"), description=t("description"), color=0x0284C7
        )

        return dict(embed=embed, component=component)

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

        await channel.send(**self.get_message(guild))

    async def migrate_embed(self, message: hikari.Message, guild: hikari.GatewayGuild):
        await message.edit(**self.get_message(guild))

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
