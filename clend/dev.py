from datetime import datetime, timezone
import sys
import typing

import hikari

from .bot import TheCleaner


DEVELOPERS = {
    633993042755452932,
}


class DevExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    dependencies: list[str]

    def __init__(self, bot: TheCleaner) -> None:
        self.bot = bot
        self.extensions = [
            "clend.guild",
            "clend.http",
        ]
        self.listeners = [
            (hikari.GuildMessageCreateEvent, self.on_message_create),
        ]
        self.dependencies = []

    def on_load(self):
        for ext in self.extensions:
            self.bot.load_extension(ext)
    
    def on_unload(self):
        for ext in self.extensions:
            self.bot.unload_extension(ext)

    async def on_message_create(self, event: hikari.GuildMessageCreateEvent):
        if event.author_id not in DEVELOPERS:
            return
        if event.content == "clean!ping":
            await self.handle_ping(event)
        elif event.content == "clean!reload-all":
            await self.handle_reload_all(event)
        elif event.content == "clean!stop":
            await self.handle_stop(event)

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

    async def handle_reload_all(self, event: hikari.GuildMessageCreateEvent):
        msg = await event.message.respond("Reloading all extensions...")
        for mod in tuple(sys.modules.keys()):
            if mod.startswith("clend"):
                del sys.modules[mod]
        for ext in self.extensions:
            self.bot.reload_extension(ext)
        await msg.edit(f"Reloaded {len(self.extensions)} extensions!")

    async def handle_stop(self, event: hikari.GuildMessageCreateEvent):
        await event.message.respond("Bye!")
        await self.bot.bot.close()


extension = DevExtension
