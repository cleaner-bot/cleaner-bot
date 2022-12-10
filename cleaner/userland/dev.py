from __future__ import annotations

import asyncio
import logging
import sys
import typing
from pathlib import Path

import hikari
from hikari.internal.time import utc_datetime

from ._types import ConfigType, EntitlementsType, KernelType
from .helpers.embedize import embedize_guild, embedize_user
from .helpers.settings import get_config, get_entitlements, set_config, set_entitlements

logger = logging.getLogger(__name__)


class DeveloperService:
    commands: dict[str, typing.Callable[..., typing.Awaitable[None]]]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.bindings["dev"] = self.message_create

        self.commands = {
            "help": self.help_command,
            "ping": self.ping_command,
            "reload": self.reload_command,
            "lookup": self.lookup_command,
            "guilds": self.guilds_command,
            "info": self.info_command,
            "register-slash": lambda x: self.register_slash_commands(x, False),
            "register-slash-global": lambda x: self.register_slash_commands(x, True),
            "reset-slash": self.reset_slash_commands,
            "get-config": self.get_config,
            "set-config": self.set_config,
            "get-entitlement": self.get_entitlement,
            "set-entitlement": self.set_entitlement,
            "load-data": self.load_data,
            "save-data": self.save_data,
            "button": self.button,
            "git-pull": self.git_pull,
            "get-captcha-data": self.get_captcha_data,
            "members-scan": self.members_scan,
            "threads-cache": self.threads_cache,
        }

    async def message_create(
        self,
        message: hikari.Message,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> None:
        content = message.content
        if not content or not content.startswith(">"):
            return

        args = content[1:].split()
        command = self.commands.get(args[0], None)
        if command is None:
            return

        try:
            await command(message, *args[1:])
        except Exception as e:
            logger.exception("error during command execution", exc_info=e)
            await message.respond(
                "error during command execution, check logs", reply=message
            )

    async def help_command(self, message: hikari.Message) -> None:
        await message.respond(
            "**developer mode**\n" "commands: " + ", ".join(self.commands.keys())
        )

    async def ping_command(self, message: hikari.Message) -> None:
        sent = utc_datetime()
        ws_latency = self.kernel.bot.heartbeat_latency * 1000

        msg = await message.respond(
            f"Websocket latency: **{ws_latency:.2f}ms**\n" f"API latency: *fetching*",
        )
        api_latency = (msg.created_at - sent).total_seconds() * 1000
        await msg.edit(
            f"Websocket latency: **{ws_latency:.2f}ms**\n"
            f"API latency: **{api_latency:.2f}ms**"
        )

    async def reload_command(
        self, message: hikari.Message, name: str | None = None
    ) -> None:
        if name is None or name.count(":") == 0:
            await message.respond("nice module name")
            return

        msg = await message.respond(f"Reloading `{name}`")

        if name in self.kernel.extensions:
            try:
                self.kernel.unload_extension(name)
            except Exception as e:
                logger.error(f"Error unloading {name}", exc_info=e)
                await msg.edit("Failed. Unload error.")
                return

        reloaded = []
        module_name = name.split(":")[0]
        for module in tuple(sys.modules):
            if module == module_name or module.startswith(f"{module_name}."):
                del sys.modules[module]
                reloaded.append(module)

        logger.info("reloaded modules " + ", ".join(reloaded))

        try:
            self.kernel.load_extension(name)
        except ModuleNotFoundError as e:
            if e.name == name:
                await msg.edit("Failed because I did not find the extension, idiot.")
                return
            logger.error(f"Error loading {name}", exc_info=e)
            await msg.edit("Failed. Load error.")
        except Exception as e:
            logger.error(f"Error loading {name}", exc_info=e)
            await msg.edit("Failed. Load error.")
        else:
            await msg.edit(
                "Success. Reloaded modules: " + ", ".join(f"`{x}`" for x in reloaded)
            )

    async def lookup_command(self, message: hikari.Message, user_or_guild: str) -> None:
        as_int = int(user_or_guild)
        guild = self.kernel.bot.cache.get_guild(as_int)
        if guild is not None:
            owner = self.kernel.bot.cache.get_user(guild.owner_id)
            if owner is None:
                owner = await self.kernel.bot.rest.fetch_user(guild.owner_id)

            entitlements = await get_entitlements(self.kernel, guild.id)

            await message.respond(
                "Found a matching guild and its owner.",
                embeds=[
                    await embedize_guild(guild, self.kernel.bot, entitlements, owner),
                    embedize_user(owner),
                ],
            )
            return

        user = self.kernel.bot.cache.get_user(as_int)
        if user is None:
            try:
                user = await self.kernel.bot.rest.fetch_user(as_int)
            except hikari.NotFoundError:
                await message.respond("No matching user or guild found.")
                return

        component = self.kernel.bot.rest.build_message_action_row()
        (
            component.add_button(
                hikari.ButtonStyle.LINK, f"discord://-/users/{user.id}"
            )
            .set_label("Show profile")
            .add_to_container()
        )
        await message.respond(
            "Found a matching user.", embed=embedize_user(user), component=component
        )

    async def guilds_command(self, message: hikari.Message) -> None:
        guilds = sorted(
            (
                (x, x.member_count)
                for x in self.kernel.bot.cache.get_guilds_view().values()
                if x.member_count is not None
            ),
            key=lambda x: x[1],
            reverse=True,
        )

        largest_len = len(f"{guilds[0][1]:,}")
        await message.respond(
            "Top 20 largest guilds:\n"
            + "\n".join(
                "`" + f"{y:,}".rjust(largest_len) + f"` - {x.name} ({x.id})"
                for x, y in guilds
            )
        )

    async def info_command(self, message: hikari.Message) -> None:
        guild_count = len(self.kernel.bot.cache.get_guilds_view())
        cached_user_count = len(self.kernel.bot.cache.get_users_view())
        cached_member_count = sum(
            len(self.kernel.bot.cache.get_members_view_for_guild(guild))
            for guild in self.kernel.bot.cache.get_guilds_view()
        )
        approximate_member_count = sum(
            guild.member_count
            for guild in self.kernel.bot.cache.get_guilds_view().values()
            if guild.member_count
        )
        accurate_member_count = 0
        if member_counts := self.kernel.longterm.get("member_counts"):
            accurate_member_count = sum(member_counts.values())

        stats = [
            (accurate_member_count, "total users (estimated + precise tracking)"),
            (approximate_member_count, "total users (estimated)"),
            (cached_user_count, "users in cache"),
            (cached_member_count, "members in cache"),
        ]
        longest = max(len(f"{count:,}") for count, _ in stats)
        await message.respond(
            f"Guilds: {guild_count:,}\n"
            f"Users: \n"
            + "\n".join(
                "- `" + f"{count:,}".rjust(longest) + "` " + name
                for count, name in stats
            ),
            reply=message,
        )

    async def register_slash_commands(
        self, message: hikari.Message, is_global: bool
    ) -> None:
        rest = self.kernel.bot.rest
        commands = [
            rest.slash_command_builder("about", "General information about the Bot"),
            rest.slash_command_builder(
                "dashboard", "Get a link to the dashboard of this server"
            ).set_is_dm_enabled(False),
            rest.slash_command_builder("invite", "Get an invite link for The Cleaner"),
            rest.slash_command_builder("login", "Get a link to login to the dashboard"),
            # rest.slash_command_builder("auth", "Authenticate")
            # .set_default_member_permissions(0)
            # .set_is_dm_enabled(False),
            rest.context_menu_command_builder(
                hikari.CommandType.MESSAGE, "Report to server staff"
            )
            .set_default_member_permissions(0)
            .set_is_dm_enabled(False),
            rest.context_menu_command_builder(
                hikari.CommandType.MESSAGE, "Report as phishing"
            )
            .set_default_member_permissions(
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_MESSAGES
            )
            .set_is_dm_enabled(False),
        ]

        bot = self.kernel.bot.cache.get_me()
        assert bot

        await rest.set_application_commands(
            application=bot.id,
            commands=commands,
            guild=(
                hikari.UNDEFINED
                if is_global or message.guild_id is None
                else message.guild_id
            ),
        )
        await message.add_reaction("👍")

    async def reset_slash_commands(self, message: hikari.Message) -> None:
        bot = self.kernel.bot.cache.get_me()
        assert bot is not None
        await self.kernel.bot.rest.set_application_commands(
            application=bot.id,
            commands=[],
            guild=hikari.UNDEFINED if message.guild_id is None else message.guild_id,
        )
        await message.add_reaction("👍")

    async def get_config(self, message: hikari.Message, field: str) -> None:
        assert message.guild_id
        config = await get_config(self.kernel, message.guild_id)
        await message.respond(repr(config.get(field)), reply=message)

    async def set_config(self, message: hikari.Message, field: str, value: str) -> None:
        assert message.guild_id
        raw_value = eval(value)
        await set_config(self.kernel.database, message.guild_id, {field: raw_value})
        await message.add_reaction("👍")

    async def get_entitlement(self, message: hikari.Message, field: str) -> None:
        assert message.guild_id
        config = await get_entitlements(self.kernel, message.guild_id)
        await message.respond(repr(config.get(field)), reply=message)

    async def set_entitlement(
        self, message: hikari.Message, field: str, value: str
    ) -> None:
        assert message.guild_id
        raw_value = eval(value)
        await set_entitlements(
            self.kernel.database, message.guild_id, {field: raw_value}
        )
        await message.add_reaction("👍")

    async def load_data(self, message: hikari.Message, name: str | None = None) -> None:
        load_data = self.kernel.bindings["data:load"]
        load_data(name)
        await message.add_reaction("👍")

    async def save_data(self, message: hikari.Message, name: str | None = None) -> None:
        save_data = self.kernel.bindings["data:save"]
        save_data(name)
        await message.add_reaction("👍")

    async def button(self, message: hikari.Message, custom_id: str) -> None:
        component = self.kernel.bot.rest.build_message_action_row()
        (
            component.add_button(hikari.ButtonStyle.SECONDARY, custom_id)
            .set_label("?")
            .add_to_container()
        )
        await message.respond(component=component, reply=True)

    async def git_pull(self, message: hikari.Message) -> None:
        command = "git pull"
        msg = await message.respond(f"Running `{command}`")

        pip = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await pip.communicate()
        log = (stdout.decode() if stdout else "") + (stderr.decode() if stderr else "")
        await message.respond(
            f"```\n{log[:1900]}```" if message else "Done. (no output)", reply=msg
        )

    async def get_captcha_data(self, original_message: hikari.Message) -> None:
        from httpx import AsyncClient

        from .captcha.dataset import datasets, load_dataset, origin

        channels = self.kernel.bot.cache.get_guild_channels_view_for_guild(
            963042403474882600
        )
        new: dict[str, int] = {}
        tasks = []
        client = AsyncClient(
            http2=True,
            headers={"user-agent": "CleanerBot (cleanerbot.xyz, 0.1.0)"},
            timeout=30,
        )

        async def download_image(url: str, out: Path) -> None:
            loop = asyncio.get_running_loop()
            raw_image = await client.get(url + "?width=100&height=100")
            await loop.run_in_executor(None, out.write_bytes, raw_image.content)

        for channel in channels.values():
            if channel.parent_id is None or channel.name not in (
                "cat",
                "dog",
                "rabbit",
                "hedgehog",
                "bird",
            ):
                continue
            parent_channel = channels[channel.parent_id]
            assert parent_channel.name
            if "captcha" not in parent_channel.name.lower():
                continue

            assert channel.name
            (origin / channel.name).mkdir(exist_ok=True, parents=True)
            messages = self.kernel.bot.rest.fetch_messages(channel.id)
            total = 0
            async for message in messages:
                if not message.attachments:
                    continue
                if (origin / channel.name / f"{message.id}.jpg").exists():
                    break
                for i, attachment in enumerate(message.attachments):
                    out = origin / channel.name / f"{message.id + i}.jpg"
                    tasks.append(
                        asyncio.ensure_future(download_image(attachment.proxy_url, out))
                    )
                    total += 1

                if len(tasks) > 5000:
                    await asyncio.gather(*tasks)
                    logger.debug(f"performed {len(tasks)} downloads")
                    client = AsyncClient(
                        http2=True,
                        headers={"user-agent": "CleanerBot (cleanerbot.xyz, 0.1.0)"},
                        timeout=30,
                    )
                    tasks.clear()

            if total:
                logger.debug(f"downloading {total} for {channel.name}")

            new[channel.name] = total

        if tasks:
            await asyncio.gather(*tasks)
            logger.debug(f"performed {len(tasks)} downloads")
            client = AsyncClient(
                http2=True,
                headers={"user-agent": "CleanerBot (cleanerbot.xyz, 0.1.0)"},
                timeout=30,
            )

        if tasks:
            load_dataset()

        prompts = sorted(
            ((k, len(v)) for k, v in datasets.items()), key=lambda x: x[1], reverse=True
        )
        largest_len = len(f"{prompts[0][1]:,}")
        await original_message.respond(
            "Datasets:\n"
            + "\n".join(
                "`"
                + f"{count:,}".rjust(largest_len)
                + f"` - {name} (`{new.get(name, 0):+}`)"
                for name, count in prompts
            )
        )
        unknown = datasets.keys() - new
        if unknown:
            await original_message.respond(
                ":warning: Couldn't find the following datasets, but they "
                "are still downloaded!\n" + ", ".join(unknown)
            )

    async def members_scan(self, message: hikari.Message) -> None:
        from .helpers.binding import complain_if_none, safe_call

        if members_timer := complain_if_none(
            self.kernel.bindings.get("members:timer"), "data:save"
        ):
            await safe_call(members_timer(), True)

        await message.add_reaction("👍")

    async def threads_cache(self, message: hikari.Message) -> None:
        threads = self.kernel.bot.cache.get_threads_view()
        await message.respond(
            f"{len(threads)} threads.\n\n"
            + "\n".join(f"`{x.id}` {x.name}" for x in threads.values())
        )
