import logging
import typing

import hikari

from ..bot import TheCleaner
from ..shared.id import time_passed_since

logger = logging.getLogger(__name__)


class ReportExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.InteractionCreateEvent, self.on_interaction_create),
        ]
        self.task = None

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent):
        interaction = event.interaction
        print(interaction)
        if not isinstance(interaction, hikari.MessageInteraction):
            return
        elif not interaction.custom_id.startswith("challenge"):
            return
        elif (passed := time_passed_since(interaction.id).total_seconds()) >= 2.5:
            return

        logger.debug("used report context menu")


