import asyncio
from datetime import datetime, timezone
import logging
import sys
import typing

import hikari

from .bot import TheCleaner


logger = logging.getLogger(__name__)


class DevExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner) -> None:
        self.bot = bot
        self.extensions = [
            "clend.timer",
            "clend.conf",
            "clend.http",
            "clend.guild",
            "clend.challenge",
            "clend.verification",
            "clend.sync",
            "clend.slash",
            "clend.analytics",
            "clend.downdoom",
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
        elif event.content in ("clean!register-slash", "clean!register-slash-global"):
            await self.handle_register_slash(event)
        elif event.content == "clean!info":
            await self.handle_info(event)
        elif event.content == "clean!pull":
            await self.handle_pull(event)
        elif event.content == "clean!update":
            await self.handle_update(event)

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

    async def handle_register_slash(self, event: hikari.GuildMessageCreateEvent):
        is_global = event.content and event.content.endswith("-global")

        commands = [
            event.app.rest.slash_command_builder(
                "about", "General information about the Bot"
            ),
            event.app.rest.slash_command_builder(
                "dashboard", "Get a link to the dashboard of this server"
            ),
            event.app.rest.slash_command_builder(
                "invite", "Get an invite link for The Cleaner"
            ),
            # event.app.rest.slash_command_builder(
            #     "login", "Create a link to login immediately (useful for phones)"
            # ),
        ]

        me = self.bot.bot.get_me()
        if me is None:
            return await event.message.respond("no me found")
        await event.app.rest.set_application_commands(
            application=me.id,
            commands=commands,
            guild=hikari.UNDEFINED if is_global else event.guild_id,
        )

        await event.message.respond("done")

    async def handle_info(self, event: hikari.GuildMessageCreateEvent):
        bot = self.bot.bot
        guilds = len(bot.cache.get_guilds_view())
        users = len(bot.cache.get_users_view())
        members = sum(
            len(bot.cache.get_members_view_for_guild(guild))
            for guild in bot.cache.get_guilds_view()
        )
        await event.message.respond(
            f"__Total__:\n"
            f"Guilds: {guilds}\n\n"
            f"__Cache stats__\n"
            f"Users: {users}\n"
            f"Members: {members}\n"
        )

    async def handle_pull(self, event: hikari.GuildMessageCreateEvent):
        msg = await event.message.respond("Pulling from git")
        git_pull = await asyncio.create_subprocess_shell(
            "git pull", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await git_pull.communicate()
        message = (stdout.decode() if stdout else "") + (
            stderr.decode() if stderr else ""
        )
        await msg.edit(f"```\n{message}```" if message else "Done. (no output)")

    async def handle_update(self, event: hikari.GuildMessageCreateEvent):
        if event.message.content is None:
            return  # impossible, but makes mypy happy
        name = event.message.content[13:]
        msg = await event.message.respond(f"Updating `{name}`")
        pip = await asyncio.create_subprocess_shell(
            f"{sys.executable} -m pip install -U {msg}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await pip.communicate()
        message = (stdout.decode() if stdout else "") + (
            stderr.decode() if stderr else ""
        )
        await msg.edit(f"```\n{message}```" if message else "Done. (no output)")


extension = DevExtension
