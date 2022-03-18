import logging
import typing

import hikari
from hikari.internal.time import utc_datetime

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
        if not isinstance(interaction, hikari.CommandInteraction):
            return

        age = (utc_datetime() - interaction.created_at).total_seconds()
        if age > 3:
            logger.error(f"received interaction that is older than 3s ({age:.3f}s)")
        elif age > 1:
            logger.warning(f"received interaction that is older than 1s ({age:.3f}s)")
        else:
            logger.debug(f"got interaction with age {age:.3f}s")

        try:
            if interaction.command_name == "about":
                await self.handle_about(interaction)
            elif interaction.command_name == "dashboard":
                await self.handle_dashboard(interaction)
        except Exception as e:
            logger.exception("Error occured during component interaction", exc_info=e)
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    "**Internal error**: Something went wrong on our end.\n"
                    "**Please contact support!**"
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

    async def handle_about(self, interaction: hikari.CommandInteraction):
        component1 = interaction.app.rest.build_action_row()
        add_link(component1, "Website", "https://cleaner.leodev.xyz")
        add_link(component1, "Documentation", "https://cleaner.leodev.xyz/docs/")
        add_link(component1, "Blog", "https://cleaner.leodev.xyz/blog/")
        component2 = interaction.app.rest.build_action_row()
        add_link(
            component2, "Privacy Policy", "https://cleaner.leodev.xyz/legal/privacy"
        )
        add_link(
            component2, "Terms of Service", "https://cleaner.leodev.xyz/legal/terms"
        )
        add_link(component2, "Impressum", "https://cleaner.leodev.xyz/legal/impressum")
        component3 = interaction.app.rest.build_action_row()
        add_link(component3, "Support server", "https://cleaner.leodev.xyz/discord")
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "The Cleaner is a Discord bot designed to keep your server clean "
            "and safe. (basically a very good auto moderator)",
            components=[component1, component2, component3],
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def handle_dashboard(self, interaction: hikari.CommandInteraction):
        member = interaction.member

        if member is None:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                "This command can only be used in a server.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        component = interaction.app.rest.build_action_row()
        add_link(
            component,
            "Dashboard",
            f"https://cleaner.leodev.xyz/dash/{interaction.guild_id}",
        )

        note = None
        if not member.permissions & (
            hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD
        ):
            note = (
                ":warning: You do not have `ADMINISTRATOR` or `MANAGE SERVER` "
                "permission, so you cannot access this server's dashboard."
            )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "Click the button below to go to your dashboard!"
            + (f"\n\n{note}" if note is not None else ""),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )
