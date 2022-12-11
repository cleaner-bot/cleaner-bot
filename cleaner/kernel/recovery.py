"""
Recovery mode that is loaded when the kernel fails to load.
"""

import asyncio
import logging
import typing

import hikari

from ._types import HypervisorType

logger = logging.getLogger(__name__)


class CleanerRecovery:
    commands: dict[str, typing.Callable[..., typing.Awaitable[None]]]

    def __init__(self, hypervisor: HypervisorType) -> None:
        self.hypervisor = hypervisor
        logger.warning("recovery mode has been loaded")

        self.hypervisor.bot.subscribe(hikari.MessageCreateEvent, self.on_message_create)
        self.commands = {
            "help": self.help_command,
            "reload": self.reload_command,
            "run": self.run_command,
        }

    def unload(self) -> None:
        self.hypervisor.bot.unsubscribe(
            hikari.MessageCreateEvent, self.on_message_create
        )

    async def on_message_create(self, event: hikari.MessageCreateEvent) -> None:
        if event.author_id != 647558454491480064:
            return

        content = event.message.content
        if not content or not content.startswith("!"):
            return

        args = content[1:].split()
        command = self.commands.get(args[0], None)
        if command is None:
            return

        try:
            await command(event.message, *args[1:])
        except Exception as e:
            logger.exception("error during command execution", exc_info=e)
            await event.message.respond(
                "error during command execution, check logs", reply=event.message
            )

    async def help_command(self, event: hikari.MessageCreateEvent) -> None:
        await event.message.respond(
            "**recovery mode**\n" "commands: " + ", ".join(self.commands.keys())
        )

    async def reload_command(self, event: hikari.MessageCreateEvent) -> None:
        await event.message.respond("reloading")
        self.unload()

        self.hypervisor.reload()

    async def run_command(
        self, event: hikari.MessageCreateEvent, *command_parts: str
    ) -> None:
        command = " ".join(command_parts)
        msg = await event.message.respond(f"Running `{command}`")

        pip = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await pip.communicate()
        message = (stdout.decode() if stdout else "") + (
            stderr.decode() if stderr else ""
        )
        await event.message.respond(
            f"```\n{message[:1900]}```" if message else "Done. (no output)", reply=msg
        )
