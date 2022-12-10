import typing

import hikari

from ._types import ConfigType, InteractionResponse, KernelType
from .helpers.binding import complain_if_none, safe_call
from .helpers.invite import generate_invite
from .helpers.localization import Message
from .helpers.settings import get_config

ACCESS_NOBODY, ACCESS_ADMINS, ACCESS_MANAGERS = range(3)


class AuthService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "auth-select": self.auth_select_menu,
            "auth-enter-totp": self.auth_enter_totp,
        }

        self.kernel.interactions["commands"]["auth"] = self.auth_command
        self.kernel.interactions["components"].update(components)

    async def auth_command(
        self, interaction: hikari.CommandInteraction
    ) -> InteractionResponse:
        assert interaction.guild_id
        assert interaction.member
        config = await get_config(self.kernel, interaction.guild_id)
        guild = interaction.get_guild()
        assert guild is not None

        if not config["auth_enabled"]:
            return {
                "content": Message("commands_auth_disabled").translate(
                    self.kernel, interaction.locale
                )
            }

        is_owner = interaction.user.id == guild.owner_id

        available_role_ids: list[str] = []
        if is_owner:
            available_role_ids.extend(config["auth_roles"].keys())
        else:
            for role_id in config["auth_roles"].keys():
                if self.can_get_role(interaction.member, config, role_id):
                    available_role_ids.append(role_id)

        available_roles: list[hikari.Role] = [
            role for role_id in available_roles if (role := guild.get_role(role_id))
        ]

        if not available_roles:
            return {
                "content": Message("commands_auth_notfound").translate(
                    self.kernel, interaction.locale
                )
            }

        mfa_type = await self.kernel.database.hget(
            f"user:{interaction.user.id}:mfa", "type"
        )
        if mfa_type is None:
            row = self.kernel.bot.rest.build_message_action_row()
            (
                row.add_button(
                    hikari.ButtonStyle.LINK,
                    generate_invite(self.kernel.bot, False, True, "mfa"),
                )
                .set_label("MFA")
                .add_to_container()
            )
            return {
                "content": Message("commands_auth_nomfa").translate(
                    self.kernel, interaction.locale
                ),
                "component": row,
            }

        if len(available_roles) == 1 and False:
            return self.selected_role(interaction, available_roles[0])

        row = self.kernel.bot.rest.build_message_action_row()
        dropdown = row.add_select_menu("auth-select")
        for role in available_roles:
            (
                dropdown.add_option(role.name, str(role.id))
                .set_description(str(role.id))
                .add_to_menu()
            )

        (dropdown.set_min_values(1).set_max_values(1).add_to_container())

        return {
            "content": Message("commands_auth_select").translate(
                self.kernel, interaction.locale
            ),
            "component": row,
        }

    async def auth_select_menu(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse | None:
        role_id = interaction.values[0]
        return await self.selected_role(interaction, role_id)

    async def selected_role(
        self,
        interaction: hikari.CommandInteraction | hikari.ComponentInteraction,
        role_id: str,
    ) -> InteractionResponse | None:
        if mfa_request := complain_if_none(
            self.kernel.bindings.get("mfa:request"), "mfa:request"
        ):
            return await safe_call(mfa_request(interaction, "auth-verified", role_id))

        return {
            "content": Message("commands_auth_mfaerror").translate(
                self.kernel, interaction.locale
            )
        }

    async def auth_enter_totp(
        self, interation: hikari.ComponentInteraction, role_id: str
    ) -> InteractionResponse | None:
        pass

    def can_get_role(
        self, member: hikari.InteractionMember, config: ConfigType, role_id: str
    ) -> bool:
        if (
            config["access_permissions"] >= ACCESS_ADMINS
            and member.permissions & hikari.Permissions.ADMINISTRATOR
        ) or (
            config["access_permissions"] >= ACCESS_MANAGERS
            and member.permissions & hikari.Permissions.MANAGE_GUILD
        ):
            return True

        user_id = str(member.id)
        if user_id in config["access_members"]:
            return True
        elif user_id in config["auth_roles"].get(role_id, []):
            return True

        return False
