import hikari

from ._types import InteractionResponse, KernelType
from .helpers.invite import generate_invite
from .helpers.localization import Message
from .helpers.settings import get_config

ACCESS_NOBODY, ACCESS_ADMINS, ACCESS_MANAGERS = range(3)


class CommandsService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        commands = {
            "about": self.about_command,
            "dashboard": self.dashboard_command,
            "invite": self.invite_command,
            "login": self.login_command,
        }

        self.kernel.interactions["commands"].update(commands)

    async def about_command(
        self, interaction: hikari.CommandInteraction
    ) -> InteractionResponse:
        return {
            "content": Message(
                "commands_about_content",
                {
                    "base": "https://cleanerbot.xyz",
                },
            ).translate(self.kernel, interaction.locale)
        }

    async def dashboard_command(
        self, interaction: hikari.CommandInteraction
    ) -> InteractionResponse:
        if interaction.guild_id is None or interaction.member is None:
            return {
                "content": Message("interaction_error_guildonly").translate(
                    self.kernel, interaction.locale
                )
            }

        config = await get_config(self.kernel, interaction.guild_id)
        guild = interaction.get_guild()
        if not (
            (guild is not None and interaction.user.id == guild.owner_id)
            or (
                config["access_permissions"] >= ACCESS_ADMINS
                and interaction.member.permissions & hikari.Permissions.ADMINISTRATOR
            )
            or (
                config["access_permissions"] >= ACCESS_MANAGERS
                and interaction.member.permissions & hikari.Permissions.MANAGE_GUILD
            )
        ):
            return {
                "content": Message("commands_dashboard_forbidden").translate(
                    self.kernel, interaction.locale
                )
            }

        component = self.kernel.bot.rest.build_message_action_row()
        component.add_link_button(
            f"https://cleanerbot.xyz/dash#{interaction.guild_id}",
            label=Message("commands_dashboard_dashboard").translate(
                self.kernel, interaction.locale
            ),
        )

        return {
            "content": Message("commands_dashboard_content").translate(
                self.kernel, interaction.locale
            ),
            "component": component,
        }

    async def invite_command(
        self, interaction: hikari.CommandInteraction
    ) -> InteractionResponse:
        component = interaction.app.rest.build_message_action_row()
        component.add_link_button(
            generate_invite(self.kernel.bot, True, True),
            label=Message("commands_invite").translate(self.kernel, interaction.locale),
        )

        return {"component": component}

    async def login_command(
        self, interaction: hikari.CommandInteraction
    ) -> InteractionResponse:
        component = interaction.app.rest.build_message_action_row()
        component.add_link_button(
            generate_invite(self.kernel.bot, False, True),
            label=Message("commands_login").translate(self.kernel, interaction.locale),
        )

        return {"component": component}
