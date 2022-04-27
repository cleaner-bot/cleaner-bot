import asyncio
import logging
import sys
import typing

import hikari
from hikari.internal.time import utc_datetime

from .bot import TheCleaner
from .shared.timing import timer_generator


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
            "clend.report",
            "clend.analytics",
            "clend.metrics",
            "clend.downdoom",
        ]
        self.listeners = [
            (hikari.GuildMessageCreateEvent, self.on_message_create),
        ]

    def on_load(self):
        timer = timer_generator()
        next(timer)  # skip first 0
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

            if (time_taken := next(timer)) >= 0.5:
                logger.info(f"spent {time_taken:.3f}s loading {ext}")

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
        if not self.bot.is_developer(event.author_id) or event.content is None:
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
        elif event.content.startswith("clean!update "):
            await self.handle_update(event)
        elif event.content.startswith("clean!reload "):
            await self.handle_reload(event)
        elif event.content.startswith("clean!emergency-ban"):
            await self.handle_emergency_ban(event)
        elif event.content == "clean!test":
            await self.handle_test(event)

    async def handle_ping(self, event: hikari.GuildMessageCreateEvent):
        sent = utc_datetime()
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
            event.app.rest.context_menu_command_builder(
                hikari.CommandType.MESSAGE, "Report to server staff"
            ),
            event.app.rest.context_menu_command_builder(
                hikari.CommandType.MESSAGE, "Report as phishing"
            ),
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
            f"{sys.executable} -m pip install -U {name!r}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await pip.communicate()
        message = (stdout.decode() if stdout else "") + (
            stderr.decode() if stderr else ""
        )
        await msg.edit(f"```\n{message}```" if message else "Done. (no output)")

    async def handle_reload(self, event: hikari.GuildMessageCreateEvent):
        if event.message.content is None:
            return  # impossible, but makes mypy happy
        name = event.message.content[13:]
        msg = await event.message.respond(f"Reloading `{name}`")

        if name in self.bot.extensions:
            try:
                self.bot.unload_extension(name)
            except Exception as e:
                logger.error(f"Error unloading {name}", exc_info=e)
                return await msg.edit("Failed. Unload error.")

        reloaded = []
        for module in tuple(sys.modules):
            if module == name or module.startswith(f"{name}."):
                del sys.modules[module]
                reloaded.append(module)

        try:
            self.bot.load_extension(name)
        except Exception as e:
            logger.error(f"Error loading {name}", exc_info=e)
            return await msg.edit("Failed. Load error.")

        await msg.edit(
            "Success. Reloaded modules: " + ", ".join(f"`{x}`" for x in reloaded)
        )

    async def handle_emergency_ban(self, event: hikari.GuildMessageCreateEvent):
        if event.message.referenced_message is None:
            await event.message.respond("You have to reply to a message.")
            return
        content = event.message.referenced_message.content
        if content is None:
            await event.message.respond("Message is empty.")
            return

        from cleaner_data.normalize import normalize
        from cleaner_data.auto.phishing_content import data

        normalized = normalize(content, normalize_unicode=False)
        data.add(normalized)

        await event.message.respond(
            "The message has been emergency banned. The ban will only exist "
            "until the next reload. Please update `cleaner-data`."
        )

    async def handle_test(self, event: hikari.GuildMessageCreateEvent):
        embed = hikari.Embed(description="a" * 4096)
        await event.message.respond(embeds=[embed, embed])


extension = DevExtension
