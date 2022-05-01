from datetime import timedelta
import logging
import typing

import hikari
from hikari import urls
from hikari.internal.time import utc_datetime

from cleaner_conf.guild import GuildConfig, GuildEntitlements
from cleaner_data.phishing_content import get_highest_phishing_match
from cleaner_data.url import has_url
from cleaner_i18n.translate import translate, Message
from expirepy.dict import ExpiringDict

from ..app import TheCleanerApp
from ..shared.id import time_passed_since
from ..shared.event import ILog
from ..shared.channel_perms import permissions_for
from ..shared.custom_events import SlowTimerEvent

logger = logging.getLogger(__name__)
REPORT_MAXAGE = 60 * 60 * 24 * 7  # 7 days
REPORT_SLOWMODE_TTL = 60 * 60 * 12  # 12 hours
REPORT_SLOWMODE_LIMIT = 3
PERMS_SEND = (
    hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.EMBED_LINKS
)


class ReportExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, app: TheCleanerApp):
        self.app = app
        self.listeners = [
            (hikari.InteractionCreateEvent, self.on_interaction_create),
            (SlowTimerEvent, self.on_slow_timer),
        ]
        self.commands = {
            "Report as phishing": self.handle_phishing_report,
            "Report to server staff": self.handle_message_report,
        }
        self.phishing_report_buttons = {
            "accept": self.handle_report_phishing_accept,
            "ban": self.handle_report_phishing_ban,
            "unban": self.handle_report_phishing_unban,
        }
        self.message_report_buttons = {
            "close": self.handle_report_message_close,
            "action": self.handle_report_message_action,
        }
        self.message_report_action_buttons = {
            "delete": self.handle_report_message_action_delete,
            "kick": self.handle_report_message_action_kick,
            "ban": self.handle_report_message_action_ban,
            "timeout_day": self.handle_report_message_action_timeout_day,
            "timeout_week": self.handle_report_message_action_timeout_week,
        }
        self.modals = {"report-message": self.handle_message_report_modal}
        self.message_cache = ExpiringDict(expires=900)

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent):
        InteractionType = hikari.CommandInteraction | hikari.ComponentInteraction
        interaction: InteractionType = event.interaction  # type: ignore

        handler = None  # type: typing.Any
        if (passed := time_passed_since(interaction.id).total_seconds()) >= 2.5:
            return

        elif isinstance(interaction, hikari.CommandInteraction):
            if interaction.command_name not in self.commands:
                return
            handler = self.commands[interaction.command_name]
            logger.debug(f"used report context menu: {interaction.command_name}")

        elif isinstance(interaction, hikari.ModalInteraction):
            parts = interaction.custom_id.split("/")
            if parts[0] not in self.modals:
                return
            handler = self.modals[parts[0]]
            logger.debug(f"used modal: {interaction.custom_id}")

        elif isinstance(interaction, hikari.ComponentInteraction):
            parts = interaction.custom_id.split("/")
            if parts[0] == "report-phishing":
                if parts[1] not in self.phishing_report_buttons:
                    return
                handler = self.phishing_report_buttons[parts[1]]

            elif parts[0] == "report-message":
                if parts[1] not in self.message_report_buttons:
                    return
                handler = self.message_report_buttons[parts[1]]

            else:
                return

            logger.debug(f"used report button: {interaction.custom_id}")

        else:
            return

        assert handler is not None

        try:
            try:
                await handler(interaction)
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
                content=translate(interaction.locale, "report_internal_error"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

    async def handle_message_report(self, interaction: hikari.CommandInteraction):
        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        channel, message = await self.is_message_report_ok(interaction)
        if channel is None or message is None:
            return  # didnt go ok

        component = interaction.app.rest.build_action_row()

        (
            component.add_text_input("reason", t("message_modal_label"))
            .set_style(hikari.TextInputStyle.PARAGRAPH)
            .set_min_length(2)
            .set_max_length(1000)
            .set_placeholder(t("message_modal_placeholder"))
            .add_to_container()
        )

        await interaction.create_modal_response(
            t("message_modal_title"),
            f"report-message/{message.id}",
            components=[component],
        )

        self.message_cache[message.id] = message

    async def handle_message_report_modal(self, interaction: hikari.ModalInteraction):
        database = self.app.database
        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        channel, message = await self.is_message_report_ok(interaction)
        if channel is None or message is None:
            return  # didnt go ok

        assert interaction.guild_id is not None

        config = self.get_config(interaction.guild_id)
        if config is None:  # dont even bother handling this
            raise RuntimeError("config is None (something went very wrong)")

        value = await database.incr(f"user:{interaction.user.id}:report:slowmode")
        if value == 1:  # first time
            await database.expire(
                f"user:{interaction.user.id}:report:slowmode",
                REPORT_SLOWMODE_TTL,
            )

        if value > REPORT_SLOWMODE_LIMIT:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("cooldown"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        await database.set(f"message:{message.id}:reported", "1", ex=REPORT_MAXAGE)

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            content=t("message_thanks"),
            flags=hikari.MessageFlag.EPHEMERAL,
        )

        embed = hikari.Embed(
            title=t("message_embed_title"), description=message.content, color=0xE74C3C
        )
        embed.set_author(
            name=f"{interaction.user} ({interaction.user.id})",
            icon=interaction.user.make_avatar_url(ext="webp", size=64),
        )
        embed.set_footer(
            f"{message.author} ({message.author.id})",
            icon=message.author.make_avatar_url(ext="webp", size=64),
        )
        embed.add_field(t("message_embed_channel"), f"<#{message.channel_id}>")

        reason = hikari.Embed(
            description=interaction.components[0].components[0].value,  # type: ignore
            color=0xE74C3C,
        ).set_author(name=t("message_embed_reason"))

        await interaction.app.rest.create_message(
            config.report_channel,
            embeds=[embed, reason],
            components=self.make_message_report_components(
                interaction, message.author.id, message.channel_id, message.id
            ),
        )

    def make_message_report_components(
        self,
        interaction: hikari.ComponentInteraction | hikari.ModalInteraction,
        message_author_id: int,
        message_channel_id: int,
        message_id: int,
        only_include: set[str] = None,
    ):
        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        assert interaction.guild_id is not None

        components = []

        component1 = interaction.app.rest.build_action_row()
        (
            component1.add_button(hikari.ButtonStyle.SECONDARY, "report-message/close")
            .set_label(t("message_button_close"))
            .add_to_container()
        )
        link = (
            f"{urls.BASE_URL}/channels/{interaction.guild_id}"
            f"/{message_channel_id}/{message_id}"
        )
        (
            component1.add_button(hikari.ButtonStyle.LINK, link)
            .set_label(t("message_button_jump"))
            .add_to_container()
        )

        components.append(component1)

        component2 = interaction.app.rest.build_action_row()
        select = component2.add_select_menu(
            f"report-message/action/{message_author_id}"
            f"/{message_channel_id}/{message_id}"
        )
        for name in ("delete", "kick", "ban", "timeout_day", "timeout_week"):
            # TODO: add permissions checks
            if only_include is not None and name not in only_include:
                continue
            select.add_option(t(f"message_action_{name}"), name).add_to_menu()
        select.set_placeholder(t("message_action_placeholder"))
        select.add_to_container()

        if select.options:
            components.append(component2)

        return components

    async def is_message_report_ok(
        self, interaction: hikari.CommandInteraction | hikari.ModalInteraction
    ):
        database = self.app.database

        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        if interaction.member is None or interaction.guild_id is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("guildonly"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        if isinstance(interaction, hikari.CommandInteraction):
            assert interaction.target_id is not None
            message_id = interaction.target_id
        else:
            parts = interaction.custom_id.split("/")
            message_id = hikari.Snowflake(parts[1])

        if time_passed_since(message_id).total_seconds() > REPORT_MAXAGE:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("too_old"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        elif await database.exists(
            (f"guild:{interaction.guild_id}:message:{message_id}:reported",)
        ):
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("already"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        message: hikari.Message | None
        if isinstance(interaction, hikari.CommandInteraction):
            assert interaction.target_id is not None
            assert interaction.resolved is not None
            message = interaction.resolved.messages.get(message_id, None)
        else:
            message = self.message_cache.get(message_id, None)
            if message is None:
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    content=t("message_modal_expired"),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return None, None

        if message is None or message.content is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("nomessage"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None
        elif message.author.is_bot:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("nobot"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None
        elif message.author.id == interaction.user.id:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("noself"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        config = self.get_config(interaction.guild_id)
        entitlements = self.get_entitlements(interaction.guild_id)
        if config is None or entitlements is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("message_nosettings"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None
        elif not config.report_channel or entitlements.report > entitlements.plan:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("message_disabled"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        guild = interaction.get_guild()
        assert guild is not None

        if message.author.id == guild.owner_id:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("message_nostaff"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        member = message.member
        if member is None:
            member = guild.get_member(message.author)
        if member is None:
            logger.debug("fetching message author :(")
            try:
                member = await self.app.bot.rest.fetch_member(guild.id, message.author)
            except hikari.NotFoundError:
                member = None

        if member is not None:
            for role_id in member.role_ids:
                if str(role_id) in config.general_modroles:
                    await interaction.create_initial_response(
                        hikari.ResponseType.MESSAGE_CREATE,
                        content=t("message_nostaff"),
                        flags=hikari.MessageFlag.EPHEMERAL,
                    )
                    return None, None
            for role in member.get_roles():
                if role.permissions & (
                    hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD
                ):
                    await interaction.create_initial_response(
                        hikari.ResponseType.MESSAGE_CREATE,
                        content=t("message_nostaff"),
                        flags=hikari.MessageFlag.EPHEMERAL,
                    )
                    return None, None

        channel = guild.get_channel(config.report_channel)
        if channel is None or channel.guild_id != interaction.guild_id:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("message_channelnotfound"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        me = guild.get_my_member()
        if me is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("message_nomyself"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        perms = permissions_for(me, channel)
        if perms & hikari.Permissions.ADMINISTRATOR:
            pass
        elif perms & PERMS_SEND != PERMS_SEND:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("message_noperms"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        return channel, message

    async def handle_report_message_close(
        self, interaction: hikari.ComponentInteraction
    ):
        await interaction.message.edit(components=[])

    async def handle_report_message_action(
        self, interaction: hikari.ComponentInteraction
    ):
        assert interaction.guild_id
        parts = interaction.custom_id.split("/")
        user_id, channel_id, message_id = map(int, parts[2:])

        action = interaction.values[0]
        if action not in self.message_report_action_buttons:
            raise RuntimeError(f"unexpected action: {action}")

        handler = self.message_report_action_buttons[action]
        msg = await handler(interaction, user_id, channel_id, message_id)

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            content=msg.translate(interaction.locale),
            flags=hikari.MessageFlag.EPHEMERAL,
        )

        action_row = interaction.message.components[1]
        assert isinstance(action_row, hikari.ActionRowComponent)
        select_menu = action_row.components[0]
        assert isinstance(select_menu, hikari.SelectMenuComponent)
        only_include = set(x.value for x in select_menu.options)
        only_include.remove(action)

        components = self.make_message_report_components(
            interaction, user_id, channel_id, message_id, only_include
        )
        await interaction.message.edit(components=components)

        simple_name = action.split("_")[0]
        log = ILog(
            interaction.guild_id,
            Message(
                f"log_user_{simple_name}", {"mod": interaction.user.id, "user": user_id}
            ),
            interaction.id.created_at,
            Message("report_message_action_reason"),
        )
        http = self.app.extensions.get("clend.http", None)
        if http is None:
            logger.warning("tried to log http extension is not loaded")
        else:
            http.queue.async_q.put_nowait(log)

    async def handle_report_message_action_delete(
        self,
        interaction: hikari.ComponentInteraction,
        user_id: int,
        channel_id: int,
        message_id: int,
    ) -> Message:
        name = "success"
        try:
            await self.app.bot.rest.delete_message(channel_id, message_id)
        except hikari.NotFoundError:
            name = "deleted"
        except hikari.ForbiddenError:
            name = "failed"
        return Message(f"report_message_action_delete_{name}")

    async def handle_report_message_action_ban(
        self,
        interaction: hikari.ComponentInteraction,
        user_id: int,
        channel_id: int,
        message_id: int,
    ) -> Message:
        name = "success"
        assert interaction.guild_id is not None
        try:
            await self.app.bot.rest.ban_member(
                interaction.guild_id, user_id, delete_message_days=1
            )
        except hikari.ForbiddenError:
            name = "failed"
        return Message(f"report_message_action_ban_{name}", {"user": user_id})

    async def handle_report_message_action_kick(
        self,
        interaction: hikari.ComponentInteraction,
        user_id: int,
        channel_id: int,
        message_id: int,
    ) -> Message:
        name = "success"
        assert interaction.guild_id is not None
        try:
            await self.app.bot.rest.kick_member(interaction.guild_id, user_id)
        except hikari.NotFoundError:
            name = "notfound"
        except hikari.ForbiddenError:
            name = "failed"
        return Message(f"report_message_action_kick_{name}", {"user": user_id})

    async def handle_report_message_action_timeout_day(
        self,
        interaction: hikari.ComponentInteraction,
        user_id: int,
        channel_id: int,
        message_id: int,
    ) -> Message:
        name = "success"
        until = utc_datetime() + timedelta(days=1)
        assert interaction.guild_id is not None
        try:
            await self.app.bot.rest.edit_member(
                interaction.guild_id, user_id, communication_disabled_until=until
            )
        except hikari.NotFoundError:
            name = "notfound"
        except hikari.ForbiddenError:
            name = "failed"
        return Message(f"report_message_action_timeout_day_{name}", {"user": user_id})

    async def handle_report_message_action_timeout_week(
        self,
        interaction: hikari.ComponentInteraction,
        user_id: int,
        channel_id: int,
        message_id: int,
    ) -> Message:
        name = "success"
        until = utc_datetime() + timedelta(days=7)
        assert interaction.guild_id is not None
        try:
            await self.app.bot.rest.edit_member(
                interaction.guild_id, user_id, communication_disabled_until=until
            )
        except hikari.NotFoundError:
            name = "notfound"
        except hikari.ForbiddenError:
            name = "failed"
        return Message(f"report_message_action_timeout_week_{name}", {"user": user_id})

    async def handle_phishing_report(self, interaction: hikari.CommandInteraction):
        database = self.app.database

        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        if interaction.member is None:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("guildonly"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        assert interaction.target_id is not None
        assert interaction.resolved is not None

        if (
            interaction.member.permissions
            & (
                hikari.Permissions.ADMINISTRATOR
                | hikari.Permissions.MANAGE_MESSAGES
                | hikari.Permissions.MANAGE_GUILD
            )
            == 0
        ):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("phishing_noperms"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        if time_passed_since(interaction.target_id).total_seconds() > REPORT_MAXAGE:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("too_old"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif await database.exists((f"message:{interaction.target_id}:reported",)):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("already"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif await database.sismember("report:phishing:banned", interaction.user.id):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("phishing_banned"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        message = interaction.resolved.messages.get(interaction.target_id, None)
        if message is None or message.content is None:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("nomessage"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif message.author.is_bot:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("nobot"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif message.author.id == interaction.user.id:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("noself"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif not has_url(message.content):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("phishing_nolink"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        match = get_highest_phishing_match(message.content)
        if match > 0.9:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("phishing_detected"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        value = await database.incr(f"user:{interaction.user.id}:report:slowmode")
        if value == 1:  # first time
            await database.expire(
                f"user:{interaction.user.id}:report:slowmode",
                REPORT_SLOWMODE_TTL,
            )

        if value > REPORT_SLOWMODE_LIMIT:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("cooldown"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        await database.set(
            f"message:{interaction.target_id}:reported", "1", ex=REPORT_MAXAGE
        )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            content=t("phishing_thanks"),
            flags=hikari.MessageFlag.EPHEMERAL,
        )

        channel_id = 968594736720019597

        embed = hikari.Embed(
            title="Phishing report", description=message.content, color=0xE74C3C
        )
        embed.set_author(
            name=f"{interaction.user} ({interaction.user.id})",
            icon=interaction.user.make_avatar_url(ext="webp", size=64),
        )
        embed.set_footer(
            f"{message.author} ({message.author.id})",
            icon=message.author.make_avatar_url(ext="webp", size=64),
        )
        embed.add_field("Channel", f"<#{message.channel_id}>")

        guild = interaction.get_guild()
        if guild is None:
            embed.add_field("Guild", str(interaction.guild_id))
        else:
            embed.add_field("Guild", f"{guild.name} ({guild.id})")

        component = interaction.app.rest.build_action_row()
        (
            component.add_button(hikari.ButtonStyle.SUCCESS, "report-phishing/accept")
            .set_label("Accept report")
            .add_to_container()
        )
        (
            component.add_button(
                hikari.ButtonStyle.DANGER, f"report-phishing/ban/{interaction.user.id}"
            )
            .set_label("Ban user from reporting")
            .add_to_container()
        )

        await interaction.app.rest.create_message(
            channel_id, embed=embed, component=component
        )

    async def handle_report_phishing_accept(
        self, interaction: hikari.ComponentInteraction
    ):
        await interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
        await interaction.message.edit(component=None)

    async def handle_report_phishing_ban(
        self, interaction: hikari.ComponentInteraction
    ):
        database = self.app.database
        parts = interaction.custom_id.split("/")
        user_id = parts[2]

        await database.sadd("report:phishing:banned", (user_id,))

        component = interaction.app.rest.build_action_row()
        (
            component.add_button(
                hikari.ButtonStyle.PRIMARY, f"report-phishing/unban/{user_id}"
            )
            .set_label("Unban")
            .add_to_container()
        )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "They have been banned and can no longer report phishing.",
            component=component,
        )

        await interaction.message.edit(component=None)

    async def handle_report_phishing_unban(
        self, interaction: hikari.ComponentInteraction
    ):
        database = self.app.database
        parts = interaction.custom_id.split("/")
        user_id = parts[2]

        await database.srem("report:phishing:banned", (user_id,))

        component = interaction.app.rest.build_action_row()
        (
            component.add_button(
                hikari.ButtonStyle.PRIMARY, f"report-phishing/ban/{user_id}"
            )
            .set_label("Ban")
            .add_to_container()
        )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "They have been unbanned.",
            component=component,
        )

        await interaction.message.edit(component=None)

    async def on_slow_timer(self, event: SlowTimerEvent):
        self.message_cache.evict()

    def get_config(self, guild_id: int) -> GuildConfig | None:
        conf = self.app.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_config(guild_id)

    def get_entitlements(self, guild_id: int) -> GuildEntitlements | None:
        conf = self.app.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_entitlements(guild_id)
