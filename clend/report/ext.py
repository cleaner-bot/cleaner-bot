import logging
import typing

import hikari

from cleaner_data.phishing_content import get_highest_phishing_match
from cleaner_data.url import has_url
from cleaner_i18n.translate import translate

from ..bot import TheCleaner
from ..shared.id import time_passed_since

logger = logging.getLogger(__name__)
REPORT_MAXAGE = 60 * 60 * 24 * 7  # 7 days
REPORT_SLOWMODE_TTL = 60 * 60 * 12  # 12 hours
REPORT_SLOWMODE_LIMIT = 3


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
        }
        self.buttons = {
            "accept": self.handle_report_phishing_accept,
            "ban": self.handle_report_phishing_ban,
            "unban": self.handle_report_phishing_unban,
        }

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
        elif isinstance(interaction, hikari.ComponentInteraction):
            if not interaction.custom_id.startswith("report-phishing/"):
                return
            parts = interaction.custom_id.split("/")
            if parts[1] not in self.buttons:
                return
            handler = self.buttons[parts[1]]
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

    async def handle_phishing_report(self, interaction: hikari.CommandInteraction):
        database = self.bot.database

        if interaction.member is None:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=translate(interaction.locale, "report_guildonly"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif interaction.target_id is None:
            return  # impossible, but makes mypy happy
        elif interaction.resolved is None:
            return  # ^

        t = lambda s, **k: translate(  # noqa E731
            interaction.locale, f"report_phishing_{s}", **k
        )

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
                content=t("noperms"),
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
                content=t("banned"),
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
        elif not has_url(message.content):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("nolink"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        match = get_highest_phishing_match(message.content)
        if match > 0.9:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=t("detected"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        value = await database.incr(
            f"user:{interaction.user.id}:report:phishing:slowmode"
        )
        if value == 1:  # first time
            await database.expire(
                f"user:{interaction.user.id}:report:phishing:slowmode",
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
            content=t("thanks"),
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
