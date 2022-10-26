import typing

import hikari

from ._types import InteractionDatabaseType, InteractionResponse, KernelType
from .helpers.invite import generate_invite
from .helpers.localization import Message


class MFAService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.interactions["components"]["mfa"] = self.enter_code
        self.kernel.interactions["modals"]["mfa"] = self.verify_code
        self.kernel.bindings["mfa:request"] = self.request_mfa

    async def request_mfa(
        self,
        interaction: (
            hikari.CommandInteraction
            | hikari.ComponentInteraction
            | hikari.ModalInteraction
        ),
        callback: str,
        state: str,
    ) -> InteractionResponse:
        row = self.kernel.bot.rest.build_action_row()

        message_content = Message("mfa_content").translate(
            self.kernel, interaction.locale
        )

        mfa_type = await self.kernel.database.hget(
            f"user:{interaction.user.id}:mfa", "type"
        )
        if mfa_type is None:
            (
                row.add_button(
                    hikari.ButtonStyle.LINK,
                    generate_invite(self.kernel.bot, False, True, "mfa"),
                )
                .set_label("MFA")
                .add_to_container()
            )
            return {
                "content": Message("mfa_nomfa").translate(
                    self.kernel, interaction.locale
                ),
                "component": row,
            }

        elif mfa_type in (b"totp", b"password"):
            (
                row.add_button(
                    hikari.ButtonStyle.SECONDARY,
                    f"mfa/{mfa_type.decode()}/{callback}/{state}",
                )
                .set_label(
                    Message(f"mfa_{mfa_type.decode()}").translate(
                        self.kernel, interaction.locale
                    )
                )
                .add_to_container()
            )

        elif mfa_type == b"u2f":
            data: InteractionDatabaseType = {
                "id": interaction.id,
                "application_id": interaction.application_id,
                "token": interaction.token,
                "locale": interaction.locale,
                "state": callback,
            }
            await self.kernel.database.hset(
                f"auth:u2f:{interaction.user.id}-{interaction.id}",
                typing.cast(dict[str | bytes, str | bytes | int | float], data),
            )
            await self.kernel.database.expire(
                f"auth:u2f:{interaction.user.id}-{interaction.id}", 60 * 10
            )
            (
                row.add_button(
                    hikari.ButtonStyle.LINK,
                    generate_invite(
                        self.kernel.bot, False, True, f"mfa##auth/{interaction.id}"
                    ),
                )
                .set_label(
                    Message("mfa_u2f").translate(self.kernel, interaction.locale)
                )
                .add_to_container()
            )
            message_content += "\n\n" + Message("mfa_u2f_expire").translate(
                self.kernel, interaction.locale
            )

        else:
            return {
                "content": Message("mfa_unsupported").translate(
                    self.kernel, interaction.locale
                ),
                "components": [],
            }

        return {"content": message_content, "component": row}

    async def enter_code(
        self,
        interaction: hikari.ComponentInteraction,
        mfa_type: str,
        callback: str,
        state: str,
    ) -> InteractionResponse:
        component = self.kernel.bot.rest.build_modal_action_row()
        (
            component.add_text_input(
                "secret",
                Message(f"mfa_modal_title_{mfa_type}").translate(
                    self.kernel, interaction.locale
                ),
            )
            .set_min_length(6 if mfa_type == "totp" else 8)
            .set_max_length(6 if mfa_type == "totp" else 1000)
            .set_placeholder(
                Message(f"mfa_modal_placeholder_{mfa_type}").translate(
                    self.kernel, interaction.locale
                )
            )
            .set_style(hikari.TextInputStyle.SHORT)
            .add_to_container()
        )

        await interaction.create_modal_response(
            Message(f"mfa_modal_title_{mfa_type}").translate(
                self.kernel, interaction.locale
            ),
            f"mfa/{mfa_type}/{callback}/{state}",
            [component],
        )

        return {}

    async def verify_code(
        self,
        interaction: hikari.ModalInteraction,
        mfa_type: str,
        callback: str,
        state: str,
    ) -> InteractionResponse:
        secret = typing.cast(hikari.InteractionTextInput, interaction.components[0])

        if mfa_type.encode() != await self.kernel.database.hget(
            f"user:{interaction.user.id}:mfa", "type"
        ):
            return {
                "content": Message("mfa_state").translate(
                    self.kernel, interaction.locale
                )
            }

        if mfa_type == "totp":
            pass

        elif mfa_type == "password":
            pass

        else:
            return {
                "content": Message("mfa_unsupported").translate(
                    self.kernel, interaction.locale
                )
            }
