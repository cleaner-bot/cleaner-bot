import logging
import os
import typing
from urllib.parse import urlencode

import hikari
from cleaner_i18n import translate as t
from hikari.urls import BASE_URL

from ..app import TheCleanerApp
from ..shared.button import add_link
from ..shared.id import time_passed_since

logger = logging.getLogger(__name__)


class SlashExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = [
            (hikari.InteractionCreateEvent, self.on_interaction_create),
        ]

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent) -> None:
        interaction = event.interaction
        passed = time_passed_since(interaction.id).total_seconds()

        if passed >= 2.5:
            logger.warning(f"received expired interaction ({passed:.3f}s)")
            return  # dont even bother
        else:
            logger.debug(f"received interaction with age {passed:.3f}s")

        coro = None
        if isinstance(interaction, hikari.CommandInteraction):
            if interaction.command_name == "about":
                coro = self.handle_about(interaction)
            elif interaction.command_name == "dashboard":
                coro = self.handle_dashboard(interaction)
            elif interaction.command_name == "invite":
                coro = self.handle_invite(interaction)
            elif interaction.command_name == "login":
                coro = self.handle_login(interaction)

            if coro is not None:
                logger.debug(f"used slash command: {interaction.command_name}")

        elif isinstance(interaction, hikari.ComponentInteraction):
            if interaction.custom_id == "login":
                coro = self.handle_login_button(interaction)

            if coro is not None:
                logger.debug(f"used button command: {interaction.custom_id}")

        else:
            return

        if coro is None:
            return

        try:
            try:
                await coro
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
            # mypy is being weird here, thinking that interaction is ModalResponseMixin
            await interaction.create_initial_response(  # type: ignore
                hikari.ResponseType.MESSAGE_CREATE,
                content=t(interaction.locale, "slash_internal_error"),  # type: ignore
                flags=hikari.MessageFlag.EPHEMERAL,
            )

    async def handle_about(self, interaction: hikari.CommandInteraction) -> None:
        component1 = interaction.app.rest.build_action_row()
        locale = interaction.locale
        add_link(component1, t(locale, "slash_about_website"), "https://cleanerbot.xyz")
        add_link(
            component1,
            t(locale, "slash_about_documentation"),
            "https://cleanerbot.xyz/docs/",
        )
        add_link(
            component1, t(locale, "slash_about_blog"), "https://cleanerbot.xyz/blog/"
        )
        component2 = interaction.app.rest.build_action_row()
        add_link(
            component2,
            t(locale, "slash_about_privacy"),
            "https://cleanerbot.xyz/legal/privacy",
        )
        add_link(
            component2,
            t(locale, "slash_about_terms"),
            "https://cleanerbot.xyz/legal/terms",
        )
        add_link(
            component2,
            t(locale, "slash_about_impressum"),
            "https://cleanerbot.xyz/legal/impressum",
        )
        component3 = interaction.app.rest.build_action_row()
        add_link(
            component3,
            t(locale, "slash_about_discord"),
            "https://cleanerbot.xyz/discord",
        )
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            t(locale, "slash_about_content"),
            components=[component1, component2, component3],
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_dashboard(self, interaction: hikari.CommandInteraction) -> None:
        member = interaction.member

        locale = interaction.locale

        if member is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                t(locale, "slash_dahsboard_guildonly"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        component = interaction.app.rest.build_action_row()
        add_link(
            component,
            t(locale, "slash_dashboard_dashboard"),
            f"https://cleanerbot.xyz/dash/{interaction.guild_id}",
        )

        note = None
        if not member.permissions & (
            hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD
        ):
            note = t(locale, "slash_dashboard_note")

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            t(locale, "slash_dashboard_content")
            + (f"\n\n{note}" if note is not None else ""),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_invite(self, interaction: hikari.CommandInteraction) -> None:
        base = "/oauth2/authorize"
        permissions = (
            hikari.Permissions.BAN_MEMBERS
            | hikari.Permissions.KICK_MEMBERS
            | hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.EMBED_LINKS
            | hikari.Permissions.MANAGE_MESSAGES
            | hikari.Permissions.MANAGE_GUILD
            | hikari.Permissions.MANAGE_CHANNELS
            | hikari.Permissions.MANAGE_ROLES
            | hikari.Permissions.MANAGE_NICKNAMES
            | hikari.Permissions.MODERATE_MEMBERS
        )
        client_id = os.getenv("discord/client-id")
        if client_id is None:
            client_id = str(self.app.store.ensure_bot_id())

        query = {
            "client_id": client_id,
            "redirect_uri": "https://cleanerbot.xyz/oauth-comeback",
            "response_type": "code",
            "scope": " ".join(
                [
                    hikari.OAuth2Scope.IDENTIFY,
                    hikari.OAuth2Scope.GUILDS,
                    hikari.OAuth2Scope.BOT,
                    hikari.OAuth2Scope.APPLICATIONS_COMMANDS,
                ]
            ),
            "state": "1",
            "prompt": "none",
            "permissions": str(int(permissions)),
        }

        url = f"{BASE_URL}{base}?{urlencode(query)}"
        component = interaction.app.rest.build_action_row()
        add_link(component, "Invite link", url)

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_login(self, interaction: hikari.CommandInteraction) -> None:
        locale = interaction.locale
        database = self.app.database

        if not await database.exists((f"user:{interaction.user.id}:oauth:token",)):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                t(locale, "nosession"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        component = interaction.app.rest.build_action_row()
        (
            component.add_button(hikari.ButtonStyle.DANGER, "login")
            .set_label(t(locale, "slash_login_proceed"))
            .add_to_container()
        )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            t(locale, "slash_login_content"),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_login_button(
        self, interaction: hikari.ComponentInteraction
    ) -> None:
        locale = interaction.locale
        database = self.app.database

        code = os.urandom(32).hex()
        await database.set(f"remote-auth:{code}", interaction.user.id, ex=300)

        component = interaction.app.rest.build_action_row()
        add_link(component, "Login", f"https://cleanerbot.xyz/remote-auth?code={code}")

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            t(locale, "slash_login_success"),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )
