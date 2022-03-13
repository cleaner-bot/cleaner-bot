from datetime import datetime, timezone
import logging
import typing

import hikari

from .bot import TheCleaner


logger = logging.getLogger(__name__)


class DevExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner) -> None:
        self.bot = bot
        self.extensions = [
            "clend.conf",
            "clend.http",
            "clend.guild",
            "clend.challenge",
        ]
        self.listeners = [
            (hikari.GuildMessageCreateEvent, self.on_message_create),
        ]

    def on_load(self):
        for ext in self.extensions:
            if ext in self.bot.extensions:
                logger.warning(f"loading already loaded extension: {ext}")
            else:
                try:
                    self.bot.load_extension(ext)
                except Exception as e:
                    logger.exception(
                        f"An error occured while loading extension: {ext}", exc_info=e
                    )

    def on_unload(self):
        for ext in self.extensions:
            if ext in self.bot.extensions:
                try:
                    self.bot.unload_extension(ext)
                except Exception as e:
                    logger.exception(
                        f"An error occured while unloading extension: {ext}", exc_info=e
                    )
            else:
                logger.warning(f"extension was never loaded: {ext}")

    async def on_message_create(self, event: hikari.GuildMessageCreateEvent):
        if not self.bot.is_developer(event.author_id):
            return
        if event.content == "clean!ping":
            await self.handle_ping(event)
        elif event.content == "clean!stop":
            await self.handle_stop(event)
        elif event.content == "clean!test":
            await self.handle_test(event)

    async def handle_ping(self, event: hikari.GuildMessageCreateEvent):
        sent = datetime.utcnow().replace(tzinfo=timezone.utc)
        ws_latency = self.bot.bot.heartbeat_latency * 1000

        msg = await event.message.respond(
            embed=hikari.Embed(
                description=f"Websocket latency: **{ws_latency:.2f}ms**\n"
                f"API latency: *fetching*",
                color=0xE74C3C,
            )
        )
        api_latency = (msg.created_at - sent).total_seconds() * 1000
        await msg.edit(
            embed=hikari.Embed(
                description=(
                    f"Websocket latency: **{ws_latency:.2f}ms**\n"
                    f"API latency: **{api_latency:.2f}ms**"
                ),
                color=0xE74C3C,
            )
        )

    async def handle_stop(self, event: hikari.GuildMessageCreateEvent):
        await event.message.respond("Bye!")
        await self.bot.bot.close()

    async def handle_test(self, event: hikari.GuildMessageCreateEvent):
        # TODO: remove
        component = event.app.rest.build_action_row()
        (
            component.add_button(hikari.ButtonStyle.PRIMARY, "challenge")
            .set_label("verify")
            .add_to_container()
        )
        await event.message.respond("verify", component=component)


extension = DevExtension
