import asyncio
import logging
import os
import sys
import typing

import hikari
from hikari.internal.time import utc_datetime

from ..app import TheCleanerApp

logger = logging.getLogger(__name__)


class DevExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = [
            (hikari.GuildMessageCreateEvent, self.on_message_create),
        ]

    async def on_message_create(self, event: hikari.GuildMessageCreateEvent) -> None:
        if not self.app.is_developer(event.author_id) or event.content is None:
            return
        if event.content == "clean!ping":
            await self.handle_ping(event)
        elif event.content == "clean!stop":
            await self.handle_stop(event)
        elif event.content in ("clean!register-slash", "clean!register-slash-global"):
            await self.handle_register_slash(event)
        elif event.content == "clean!reset-slash":
            await self.handle_reset_slash(event)
        elif event.content == "clean!info":
            await self.handle_info(event)
        elif event.content == "clean!pull":
            await self.handle_pull(event)
        elif event.content.startswith("clean!update "):
            await self.handle_update(event)
        elif event.content.startswith("clean!reload "):
            await self.handle_reload(event)
        elif event.content == "clean!reload-i18n":
            await self.handle_reload_i18n(event)
        elif event.content == "clean!emergency-ban":
            await self.handle_emergency_ban(event)
        elif event.content.startswith("clean!suspend "):
            await self.handle_suspend(event)
        elif event.content.startswith("clean!risk "):
            await self.handle_risk(event)
        elif event.content == "clean!test":
            await self.handle_test(event)
        elif event.content.startswith("clean!putenv "):
            await self.handle_putenv(event)
        elif event.content.startswith("clean!eval "):
            await self.handle_eval(event)
        elif event.content.startswith("clean!emergency-raid "):
            await self.handle_emergency_raid(event)

    async def handle_ping(self, event: hikari.GuildMessageCreateEvent) -> None:
        sent = utc_datetime()
        ws_latency = self.app.bot.heartbeat_latency * 1000

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

    async def handle_stop(self, event: hikari.GuildMessageCreateEvent) -> None:
        await event.message.respond("Bye!")
        await self.app.bot.close()

    async def handle_register_slash(
        self, event: hikari.GuildMessageCreateEvent
    ) -> None:
        is_global = event.content and event.content.endswith("-global")

        commands = [
            event.app.rest.slash_command_builder(
                "about", "General information about the Bot"
            ),
            event.app.rest.slash_command_builder(
                "dashboard", "Get a link to the dashboard of this server"
            ).set_is_dm_enabled(False),
            event.app.rest.slash_command_builder(
                "invite", "Get an invite link for The Cleaner"
            ),
            # event.app.rest.slash_command_builder(
            #     "login", "Create a link to login immediately (useful for phones)"
            # ),
            # event.app.rest.context_menu_command_builder(
            #     hikari.CommandType.MESSAGE, "Report to server staff"
            # ),
            event.app.rest.context_menu_command_builder(
                hikari.CommandType.MESSAGE, "Report as phishing"
            )
            .set_default_member_permissions(
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_MESSAGES
            )
            .set_is_dm_enabled(False),
        ]

        await event.app.rest.set_application_commands(
            application=self.app.store.ensure_bot_id(),
            commands=commands,
            guild=hikari.UNDEFINED if is_global else event.guild_id,
        )

        await event.message.respond("done")

    async def handle_reset_slash(self, event: hikari.GuildMessageCreateEvent) -> None:
        await event.app.rest.set_application_commands(
            application=self.app.store.ensure_bot_id(),
            commands=[],
            guild=event.guild_id,
        )

        await event.message.respond("done")

    async def handle_info(self, event: hikari.GuildMessageCreateEvent) -> None:
        bot = self.app.bot
        guilds = len(bot.cache.get_guilds_view())
        users = len(bot.cache.get_users_view())
        members = sum(
            len(bot.cache.get_members_view_for_guild(guild))
            for guild in bot.cache.get_guilds_view()
        )
        member_count = sum(
            guild.member_count
            for guild in bot.cache.get_guilds_view().values()
            if guild.member_count
        )
        accurate_member_count = self.app.store.get_user_count()
        await event.message.respond(
            f"__Total__:\n"
            f"Guilds: {guilds:,}\n"
            f"Member count (approximate): {member_count:,}\n"
            f"Member count (more accurate): {accurate_member_count:,}\n"
            f"\n__Cache stats__\n"
            f"Users: {users:,}\n"
            f"Members: {members:,}\n"
        )

    async def handle_pull(self, event: hikari.GuildMessageCreateEvent) -> None:
        msg = await event.message.respond("Pulling from git")
        git_pull = await asyncio.create_subprocess_shell(
            "git pull", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await git_pull.communicate()
        message = (stdout.decode() if stdout else "") + (
            stderr.decode() if stderr else ""
        )
        await msg.edit(f"```\n{message[:1900]}```" if message else "Done. (no output)")

    async def handle_update(self, event: hikari.GuildMessageCreateEvent) -> None:
        assert event.message.content

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
        await msg.edit(f"```\n{message[:1900]}```" if message else "Done. (no output)")

    async def handle_reload(self, event: hikari.GuildMessageCreateEvent) -> None:
        assert event.message.content
        name = event.message.content[13:]
        if name.startswith("cleaner."):
            await event.message.respond(
                f"Did you mean clend instead of cleaner????\n"
                f"If so, please enable IQ or go to sleep if it's late. "
                f"If you did mean to reload {name} then you're out of luck, "
                f"because I won't let you."
            )
            return

        msg = await event.message.respond(f"Reloading `{name}`")

        if name in self.app.extensions:
            try:
                self.app.unload_extension(name)
            except Exception as e:
                logger.error(f"Error unloading {name}", exc_info=e)
                await msg.edit("Failed. Unload error.")
                return

        reloaded = []
        for module in tuple(sys.modules):
            if module == name or module.startswith(f"{name}."):
                del sys.modules[module]
                reloaded.append(module)

        try:
            self.app.load_extension(name)
        except ModuleNotFoundError as e:
            if e.name == name:
                await msg.edit("Failed because I did not find the extension, idiot.")
                return
            logger.info(
                "reloaded modules" + ", ".join(f"`{x}`" for x in reloaded), exc_info=e
            )
            await msg.edit("Failed. Load error.")
        except Exception as e:
            logger.error(f"Error loading {name}", exc_info=e)
            logger.info(
                "reloaded modules" + ", ".join(f"`{x}`" for x in reloaded), exc_info=e
            )
            await msg.edit("Failed. Load error.")
        else:
            await msg.edit(
                "Success. Reloaded modules: " + ", ".join(f"`{x}`" for x in reloaded)
            )

    async def handle_reload_i18n(self, event: hikari.GuildMessageCreateEvent) -> None:
        msg = await event.message.respond("Reloading cleaner-i18n translations")

        reloaded = []
        name = "cleaner_i18n.locale"
        for module in tuple(sys.modules):
            if module == name or module.startswith(f"{name}."):
                del sys.modules[module]
                reloaded.append(module)

        from cleaner_i18n import core
        from cleaner_i18n.locale import localesd

        core.localesd = localesd

        await msg.edit(
            "Success. Reloaded modules: " + ", ".join(f"`{x}`" for x in reloaded)
        )

    async def handle_emergency_ban(self, event: hikari.GuildMessageCreateEvent) -> None:
        if event.message.referenced_message is None:
            await event.message.respond("You have to reply to a message.")
            return
        content = event.message.referenced_message.content
        if not content:
            await event.message.respond("Message is empty.")
            return

        from cleaner_data.auto.phishing_content import data
        from cleaner_data.normalize import normalize

        normalized = normalize(content, normalize_unicode=False)
        data.add(normalized)

        await event.message.respond(
            "The message has been emergency banned. The ban will only exist "
            "until the next reload. Please update `cleaner-data`."
        )

    async def handle_risk(self, event: hikari.GuildMessageCreateEvent) -> None:
        assert event.message.content
        parts = event.message.content.split(" ")
        user_id = int(parts[1])

        user = self.app.bot.cache.get_user(user_id)
        if user is None:
            user = await self.app.bot.rest.fetch_user(user_id)

        from ..shared.risk import calculate_risk_score

        risk = calculate_risk_score(user)

        await event.message.respond(f"risk={int(risk * 100)} ({risk:.2%})")

    async def handle_suspend(self, event: hikari.GuildMessageCreateEvent) -> None:
        assert event.message.content
        parts = event.message.content.split(" ")
        guild_id = parts[1]
        reason = " ".join(parts[2:])

        analytics = self.app.extensions.get("clend.analytics")
        if analytics is None:
            await event.message.respond("`clend.analytics` not loaded")
            return

        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            await event.message.respond("guild not found")
            return

        await analytics.suspend(guild, reason)
        await event.message.respond("suspended!")

    async def handle_test(self, event: hikari.GuildMessageCreateEvent) -> None:
        embed = hikari.Embed(description="a" * 4096)
        await event.message.respond(embeds=[embed, embed])

    async def handle_putenv(self, event: hikari.GuildMessageCreateEvent) -> None:
        assert event.message.content
        parts = event.message.content.split(" ")
        name, value = parts[1:]

        os.environ[name] = value
        await event.message.respond("done!")
        print(name, value)

    async def handle_emergency_raid(
        self, event: hikari.GuildMessageCreateEvent
    ) -> None:
        await event.message.respond(
            "getting all guild members, this might take a while"
        )
        guild = event.get_guild()
        assert guild
        assert event.content
        await self.app.bot.request_guild_members(guild)

        chunk_event: hikari.MemberChunkEvent
        async for chunk_event in self.app.bot.stream(
            hikari.MemberChunkEvent, timeout=300
        ):
            print("got chunk", chunk_event.chunk_index, "/", chunk_event.chunk_count)
            if (
                chunk_event.guild_id == guild.id
                and chunk_event.chunk_index == chunk_event.chunk_count - 1
            ):
                break

        members = guild.get_members()
        await event.message.respond(f"got {len(members)}")

        max_diff = 60 * 60
        other = hikari.Snowflake(event.content.split(" ")[1])
        raid_accounts: list[hikari.Member] = []
        for member in members.values():
            if (member.created_at - other.created_at).total_seconds() < max_diff:
                raid_accounts.append(member)

        await event.message.respond(f"identified {len(members)} raiders; banning now")

        from cleaner_i18n import Message

        from ..shared.event import IActionChallenge

        for member in raid_accounts:
            challenge = IActionChallenge(
                guild_id=member.guild_id,
                user=member,
                block=False,
                can_ban=True,
                can_kick=False,
                can_timeout=False,
                can_role=False,
                take_role=False,
                role_id=0,
                reason=Message(
                    "MANUAL ANTIRAID BAN",
                ),
                info={"name": "joinguard_bypass"},
            )
            self.app.store.put_http(challenge)

    async def handle_eval(self, event: hikari.MessageCreateEvent) -> None:
        assert event.content
        content = event.content[11:]
        print(content)
        print(eval(content))


extension = DevExtension
