import logging
import typing
from types import SimpleNamespace

import hikari

from cleaner_conf.guild import GuildConfig, GuildEntitlements
from cleaner_data.phishing_content import get_highest_phishing_match
from cleaner_data.url import has_url
from cleaner_i18n.translate import translate

from ..bot import TheCleaner
from ..shared.id import time_passed_since
from ..shared.channel_perms import permissions_for

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

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.InteractionCreateEvent, self.on_interaction_create),
        ]
        self.task = None
        self.commands = {
            "Report as phishing": self.handle_phishing_report,
            "Report to server staff": self.handle_report,
        }
        self.phishing_buttons = {
            "accept": self.handle_report_phishing_accept,
            "ban": self.handle_report_phishing_ban,
            "unban": self.handle_report_phishing_unban,
        }
        self.message_buttons = {}
        self.modals = {"report-message": self.handle_report_message}

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
            print(parts, self.modals, self.modals.get(parts[0]))
            if parts[0] not in self.modals:
                return
            handler = self.modals[parts[0]]
            logger.debug(f"used modal: {interaction.custom_id}")

        elif isinstance(interaction, hikari.ComponentInteraction):
            parts = interaction.custom_id.split("/")
            if parts[0] == "report-phishing":
                if parts[1] not in self.phishing_buttons:
                    return
                handler = self.phishing_buttons[parts[1]]

            elif parts[0] == "report-message":
                if parts[1] not in self.message_buttons:
                    return
                handler = self.message_buttons[parts[1]]

            else:
                return

            logger.debug(f"used report button: {interaction.custom_id}")

        else:
            return

        if handler is None:
            return  # impossible, but lets make mypy happy

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

    async def handle_report(self, interaction: hikari.CommandInteraction):
        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        channel, message = await self.is_message_report_ok(interaction)
        if channel is None or message is None:
            return  # didnt go ok

        component = interaction.app.rest.build_action_row()

        (
            component.add_text_input("reason", t("server_modal_label"))
            .set_style(hikari.TextInputStyle.PARAGRAPH)
            .set_min_length(2)
            .set_max_length(1000)
            .set_placeholder(t("server_modal_placeholder"))
            .add_to_container()
        )

        await interaction.create_modal_response(
            t("server_modal_title"),
            f"report-message/{message.id}",
            components=[component],
        )

        await self.bot.database.hset(
            f"message:{message.id}:content",
            {"author": message.author.id, "content": message.content},
        )

    async def handle_report_message(self, interaction: hikari.ModalInteraction):
        database = self.bot.database
        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        channel, message = await self.is_message_report_ok(interaction)
        print("channel", channel)
        if channel is None or message is None:
            return  # didnt go ok

        if interaction.guild_id is None:
            return  # impossible, but makes mypy happy
            
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
            content=t("phishing_thanks"),
            flags=hikari.MessageFlag.EPHEMERAL,
        )

        embed = hikari.Embed(
            title=t("server_embed_title"), description=message.content, color=0xE74C3C
        )
        embed.set_author(
            name=f"{interaction.user} ({interaction.user.id})",
            icon=interaction.user.make_avatar_url(ext="webp", size=64),
        )
        embed.set_footer(
            f"{message.author} ({message.author.id})",
            icon=message.author.make_avatar_url(ext="webp", size=64),
        )
        embed.add_field(t("server_embed_channel"), f"<#{message.channel_id}>")

        reason = hikari.Embed(
            description=interaction.components[0].components[0].value  # type: ignore
        )

        component1 = interaction.app.rest.build_action_row()
        (
            component1.add_button(hikari.ButtonStyle.SECONDARY, "report-message/close")
            .set_label(t("server_button_close"))
            .add_to_container()
        )
        (
            component1.add_button(
                hikari.ButtonStyle.LINK, message.make_link(interaction.guild_id)
            )
            .set_label(t("server_button_jump"))
            .add_to_container()
        )

        component2 = interaction.app.rest.build_action_row()
        select = component2.add_select_menu(
            f"report-message/action/{message.author.id}"
        )
        for name in ("delete", "kick", "ban", "timeout_day", "timeout_week"):
            # TODO: add permissions checks
            select.add_option(t(f"server_action_{name}"), name)
        select.set_placeholder(t("server_action_placeholder"))
        select.add_to_container()

        await interaction.app.rest.create_message(
            config.report_channel,
            embeds=[embed, reason],
            components=[component1, component2],
        )

    async def is_message_report_ok(
        self, interaction: hikari.CommandInteraction | hikari.ModalInteraction
    ):
        database = self.bot.database

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
            if interaction.target_id is None:
                return None, None  # impossible, but makes mypy happy
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
            if interaction.resolved is None:
                return None, None  # impossible, but makes mypy happy
            message = interaction.resolved.messages.get(message_id, None)
        else:
            content, author_id = await database.hmget(
                f"message:{message_id}", ("content", "author")
            )
            if (
                content is None
                or author_id is None
                or (author := self.bot.bot.cache.get_user(int(author_id))) is None
            ):
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    content=t("server_modal_expired"),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return None, None

            message = SimpleNamespace(
                id=message_id,
                content=content,
                is_bot=False,
                author=author,
            )  # type: ignore

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

        # TODO: prevent reporting mods

        config = self.get_config(interaction.guild_id)
        entitlements = self.get_entitlements(interaction.guild_id)
        if config is None or entitlements is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("server_nosettings"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None
        elif not config.report_channel or entitlements.report > entitlements.plan:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("server_disabled"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        guild = interaction.get_guild()
        if guild is None:
            return (
                None,
                None,
            )  # impossible, but makes mypy happy (guild_id is checked earlier)

        channel = guild.get_channel(config.report_channel)
        if channel is None or channel.guild_id != interaction.guild_id:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("server_channelnotfound"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        me = guild.get_my_member()
        if me is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("server_nomyself"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        perms = permissions_for(me, channel)
        if perms & hikari.Permissions.ADMINISTRATOR:
            pass
        elif perms & PERMS_SEND != PERMS_SEND:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("server_noperms"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return None, None

        return channel, message

    async def handle_phishing_report(self, interaction: hikari.CommandInteraction):
        database = self.bot.database

        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_{s}", **k
        )

        if interaction.member is None:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("guildonly"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif interaction.target_id is None:
            return  # impossible, but makes mypy happy
        elif interaction.resolved is None:
            return  # ^

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
        database = self.bot.database
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
        database = self.bot.database
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
