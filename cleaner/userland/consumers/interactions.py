"""
Interaction consumer.
"""

import logging
import typing

import hikari

from .._types import InteractionResponse, KernelType
from ..helpers.binding import safe_call
from ..helpers.localization import Message

logger = logging.getLogger(__name__)


class InteractionsConsumerService:
    events: tuple[
        tuple[
            typing.Type[hikari.Event],
            typing.Callable[
                [typing.Any], typing.Coroutine[typing.Any, typing.Any, None]
            ],
        ],
        ...,
    ]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.events = ((hikari.InteractionCreateEvent, self.on_interaction_create),)
        for type, callback in self.events:
            self.kernel.bot.subscribe(type, callback)

    def on_unload(self) -> None:
        for type, callback in self.events:
            self.kernel.bot.unsubscribe(type, callback)

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent) -> None:
        interaction = event.interaction

        is_modal = (
            isinstance(interaction, hikari.CommandInteraction)
            and interaction.command_name == "Report to server staff"
        ) or (
            isinstance(interaction, hikari.ComponentInteraction)
            and (
                interaction.custom_id.startswith("r-a-timeout")
                or interaction.custom_id.startswith("mfa/")
            )
        )

        # using rest cuz partialinteraction doesnt have functions for responding
        if isinstance(interaction, hikari.ComponentInteraction) and not is_modal:
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content="<a:Loading:1034775413987217439> The Cleaner is thinking...",
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif not is_modal:
            await self.kernel.bot.rest.create_interaction_response(
                interaction,
                interaction.token,
                hikari.ResponseType.DEFERRED_MESSAGE_CREATE,
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        type = ""
        response: InteractionResponse | None | typing.Literal[False] = False
        if isinstance(interaction, hikari.CommandInteraction):
            type = "command"
            name = interaction.command_name
            if commands_callback := self.kernel.interactions["commands"].get(name):
                response = await safe_call(commands_callback(interaction))

        elif isinstance(interaction, hikari.ComponentInteraction):
            type = "component"
            parts = interaction.custom_id.split("/")
            name, args = parts[0], parts[1:]
            if components_callback := self.kernel.interactions["components"].get(name):
                response = await safe_call(components_callback(interaction, *args))

        elif isinstance(interaction, hikari.ModalInteraction):
            type = "modal"
            parts = interaction.custom_id.split("/")
            name, args = parts[0], parts[1:]
            if modal_callback := self.kernel.interactions["modals"].get(name):
                response = await safe_call(modal_callback(interaction, *args))

        else:
            await self.kernel.bot.rest.edit_interaction_response(
                interaction.application_id,
                interaction.token,
                Message("interaction_error_type_notfound").translate(
                    self.kernel, getattr(interaction, "locale", "en-US")
                ),
            )
            return

        # gosh I hate mypy
        interaction = typing.cast(
            hikari.CommandInteraction
            | hikari.ComponentInteraction
            | hikari.ModalInteraction,
            interaction,
        )

        if response is False:
            response = {
                "content": Message(f"interaction_error_{type}_notfound").translate(
                    self.kernel, interaction.locale
                ),
            }
        elif response is None:
            response = {
                "content": Message("interaction_error_unknown").translate(
                    self.kernel, interaction.locale
                )
            }

        if response:
            await interaction.edit_initial_response(
                **response, replace_attachments=True
            )

        elif isinstance(interaction, hikari.ComponentInteraction) and not is_modal:
            await interaction.delete_initial_response()
