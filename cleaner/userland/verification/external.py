import base64
import hmac
import logging
import os
import typing
from binascii import crc32

import hikari
from hikari.internal.time import utc_datetime

from .._types import (
    InteractionDatabaseType,
    InteractionResponse,
    KernelType,
    RPCResponse,
)
from ..helpers.binding import complain_if_none
from ..helpers.localization import Message
from ..helpers.settings import get_config

logger = logging.getLogger(__name__)


class ExternalVerificationService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "v-chl-ext-info": self.on_info_external,
        }

        self.kernel.interactions["components"].update(components)

        self.kernel.bindings[
            "verification:external:issue"
        ] = self.issue_external_verification
        self.kernel.rpc["verification:external:verify"] = self.on_external_solve

    async def issue_external_verification(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse | None:
        assert interaction.guild_id
        raw_flow_id = interaction.user.id.to_bytes(
            8, "big"
        ) + interaction.guild_id.to_bytes(8, "big")
        verification_secret = os.getenv("BACKEND_VERIFICATION_SECRET")
        if verification_secret is None:
            logger.exception(
                "verification unavailable; BACKEND_VERIFICATION_SECRET is None"
            )
            return None  # show an internal error

        raw_flow_id += hmac.digest(
            bytes.fromhex(verification_secret), raw_flow_id, "sha256"
        )
        raw_flow_id += crc32(raw_flow_id).to_bytes(4, "big")

        flow_id = base64.urlsafe_b64encode(raw_flow_id).decode().strip("=")

        logger.debug(
            f"registered external challenge for "
            f"{interaction.user.id}@{interaction.guild_id}"
        )

        data: InteractionDatabaseType = {
            "id": str(interaction.id),
            "application_id": str(interaction.application_id),
            "token": interaction.token,
            "message_id": (
                str(interaction.message.id)
                if interaction.message.flags & hikari.MessageFlag.EPHEMERAL
                else "0"
            ),
            "locale": interaction.locale,
        }
        await self.kernel.database.hset(
            f"verification:external:{interaction.guild_id}-{interaction.user.id}",
            typing.cast(dict[str | bytes, str | bytes | int | float], data),
        )
        await self.kernel.database.expire(
            f"verification:external:{interaction.guild_id}-{interaction.user.id}",
            60 * 60,
        )

        component = self.kernel.bot.rest.build_action_row()
        (
            component.add_button(
                hikari.ButtonStyle.LINK, f"https://cleanerbot.xyz/chl#{flow_id}"
            )
            .set_label(
                Message("verification_external_link").translate(
                    self.kernel, interaction.locale
                )
            )
            .add_to_container()
        )
        (
            component.add_button(hikari.ButtonStyle.SECONDARY, "v-chl-ext-info")
            .set_label("?")
            .add_to_container()
        )

        return {
            "content": Message("verification_external_content").translate(
                self.kernel, interaction.locale
            ),
            "component": component,
        }

    async def on_external_solve(
        self, user_id: int, guild_id: int, data: InteractionDatabaseType
    ) -> RPCResponse:
        guild = self.kernel.bot.cache.get_guild(guild_id)
        if guild is None:
            return {"ok": False, "message": "guild not found", "data": None}

        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await self.kernel.bot.rest.fetch_member(guild, user_id)
            except hikari.NotFoundError:
                return {"ok": False, "message": "member not found", "data": None}

        config = await get_config(self.kernel.database, guild.id)
        interaction_expired = (
            utc_datetime() - hikari.Snowflake(data["id"]).created_at
        ).total_seconds() > 840

        logger.debug(f"verify {data}")
        if check_circumstances := complain_if_none(
            self.kernel.bindings.get("verification:check"), "verification:check"
        ):
            if response := await check_circumstances(
                guild, member, data["locale"], config
            ):
                response.setdefault("attachments", None)
                if interaction_expired:
                    pass
                elif data["message_id"] == "0":
                    try:
                        await self.kernel.bot.rest.edit_interaction_response(
                            int(data["application_id"]),
                            data["token"],
                            **response,
                        )
                    except hikari.NotFoundError:
                        pass  # message: dismissed
                else:
                    try:
                        await self.kernel.bot.rest.edit_webhook_message(
                            int(data["application_id"]),
                            data["token"],
                            int(data["message_id"]),
                            **response,
                        )
                    except hikari.NotFoundError:
                        pass  # message: dismissed
                return {
                    "ok": False,
                    "message": response.get(
                        "content",
                        response.get("content") or "unknown issue; check discord",
                    ),
                    "data": None,
                }

        if verification_solved := complain_if_none(
            self.kernel.bindings.get("verification:solved"), "verification:solved"
        ):
            response = await verification_solved(member, config, data["locale"])
            await self.kernel.database.delete((f"verification:external:{guild_id}-{user_id}",))
            if interaction_expired:
                pass
            elif data["message_id"] == "0":
                try:
                    response.setdefault("attachments", None)
                    await self.kernel.bot.rest.edit_interaction_response(
                        int(data["application_id"]),
                        data["token"],
                        **response,
                    )
                except hikari.NotFoundError:
                    pass  # message dismissed
            else:
                try:
                    response.setdefault("attachments", None)
                    await self.kernel.bot.rest.edit_webhook_message(
                        int(data["application_id"]),
                        data["token"],
                        int(data["message_id"]),
                        **response,
                    )
                except hikari.NotFoundError:
                    pass  # message dismissed
            return {"ok": True, "message": "OK", "data": None}

        else:
            return {
                "ok": False,
                "message": "internal error: solved not found",
                "data": None,
            }

    async def on_info_external(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        return {
            "content": Message("verification_external_info").translate(
                self.kernel, interaction.locale
            ),
        }
