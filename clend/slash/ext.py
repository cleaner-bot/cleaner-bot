import logging
import os
import typing

import hikari
from hikari.internal.time import utc_datetime

from cleaner_i18n.translate import translate

from ..bot import TheCleaner
from ..shared.button import add_link

logger = logging.getLogger(__name__)


class SlashExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.InteractionCreateEvent, self.on_interaction_create),
        ]

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent):
        interaction = event.interaction
        age = (utc_datetime() - interaction.created_at).total_seconds()
        if age > 3:
            logger.error(f"received interaction that is older than 3s ({age:.3f}s)")
        elif age > 1:
            logger.warning(f"received interaction that is older than 1s ({age:.3f}s)")
        else:
            logger.debug(f"got interaction with age {age:.3f}s")

        coro = None
        if isinstance(interaction, hikari.CommandInteraction):
            if interaction.command_name == "about":
                coro = self.handle_about(interaction)
            elif interaction.command_name == "dashboard":
                coro = self.handle_dashboard(interaction)
            elif interaction.command_name == "login":
                coro = self.handle_login(interaction)

        elif isinstance(interaction, hikari.ComponentInteraction):
            if interaction.custom_id == "login":
                coro = self.handle_login_button(interaction)

        else:
            return

        if coro is None:
            return

        try:
            await coro
        except Exception as e:
            logger.exception("Error occured during component interaction", exc_info=e)
            # mypy is being weird here, thinking that interaction is PartialInteraction
            await interaction.create_initial_response(  # type: ignore
                hikari.ResponseType.MESSAGE_CREATE,
                content=translate(
                    interaction.locale, "slash_internal_error"  # type: ignore
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

    async def handle_about(self, interaction: hikari.CommandInteraction):
        component1 = interaction.app.rest.build_action_row()
        locale = interaction.locale
        t = lambda s: translate(locale, f"slash_about_{s}")  # noqa E731
        add_link(component1, t("website"), "https://cleaner.leodev.xyz")
        add_link(component1, t("documentation"), "https://cleaner.leodev.xyz/docs/")
        add_link(component1, t("blog"), "https://cleaner.leodev.xyz/blog/")
        component2 = interaction.app.rest.build_action_row()
        add_link(component2, t("privacy"), "https://cleaner.leodev.xyz/legal/privacy")
        add_link(component2, t("terms"), "https://cleaner.leodev.xyz/legal/terms")
        add_link(
            component2, t("impressum"), "https://cleaner.leodev.xyz/legal/impressum"
        )
        component3 = interaction.app.rest.build_action_row()
        add_link(component3, t("discord"), "https://cleaner.leodev.xyz/discord")
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            t("content"),
            components=[component1, component2, component3],
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_dashboard(self, interaction: hikari.CommandInteraction):
        member = interaction.member

        locale = interaction.locale
        t = lambda s: translate(locale, f"slash_dashboard_{s}")  # noqa E731

        if member is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                t("guildonly"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        component = interaction.app.rest.build_action_row()
        add_link(
            component,
            t("dashboard"),
            f"https://cleaner.leodev.xyz/dash/{interaction.guild_id}",
        )

        note = None
        if not member.permissions & (
            hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD
        ):
            note = t("note")

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            t("content") + (f"\n\n{note}" if note is not None else ""),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_login(self, interaction: hikari.CommandInteraction):
        locale = interaction.locale
        t = lambda s: translate(locale, f"slash_login_{s}")  # noqa E731
        database = self.bot.database

        if not await database.exists((f"user:{interaction.user.id}:oauth:token",)):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                t("nosession"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        component = interaction.app.rest.build_action_row()
        (
            component.add_button(hikari.ButtonStyle.DANGER, "login")
            .set_label(t("proceed"))
            .add_to_container()
        )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            t("content"),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_login_button(self, interaction: hikari.ComponentInteraction):
        locale = interaction.locale
        t = lambda s: translate(locale, f"slash_login_{s}")  # noqa E731
        database = self.bot.database

        code = os.urandom(32).hex()
        await database.set(f"remote-auth:{code}", interaction.user.id, ex=300)

        component = interaction.app.rest.build_action_row()
        add_link(
            component, "Login", f"https://cleaner.leodev.xyz/remote-auth?code={code}"
        )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            t("success"),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )
