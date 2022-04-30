import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
import resource
import typing

import aiofiles
import aiofiles.os
import hikari

from ..bot import TheCleaner
from ..shared.protect import protect
from ..shared.event import ILog
from ..shared.custom_events import SlowTimerEvent

logger = logging.getLogger(__name__)
HANDLE_LIMIT = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
INITIAL_WRITES = 4


@dataclass
class OpenFileHandle:
    file_handle: aiofiles.threadpool.text.AsyncTextIOWrapper
    writes: int


class GuildLogExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    queue: asyncio.Queue[ILog]
    handles: dict[int, OpenFileHandle]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (SlowTimerEvent, self.on_slow_timer),
        ]
        self.task = None
        self.file_handle_limit = HANDLE_LIMIT // 4
        self.handles = {}
        self.queue = asyncio.Queue()
        self.now = datetime.utcnow()

    def on_load(self):
        self.task = asyncio.create_task(protect(self.logd))

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

        # cleanup job
        if self.handles:
            asyncio.create_task(self.close_all_handles())

    async def logd(self):
        while True:
            log = await self.queue.get()
            handle = await self.get_handle(log.guild_id)
            formatted_log = self.format_log(log)
            await handle.write(formatted_log)

    async def get_handle(
        self, guild_id: int
    ) -> aiofiles.threadpool.text.AsyncTextIOWrapper:
        handle = self.handles.get(guild_id, None)
        if handle is None:
            if len(self.handles) >= self.file_handle_limit:
                # reached the limit, kick the one with least writes out
                least_guild_id = min(
                    self.handles, key=lambda gid: self.handles[gid].writes
                )
                logger.debug(f"evicted {least_guild_id} file handle")
                handle = self.handles[least_guild_id]
                del self.handles[least_guild_id]
                await handle.file_handle.close()

            if not await aiofiles.os.path.exists(f"guild-log/{guild_id}"):
                await aiofiles.os.makedirs(f"guild-log/{guild_id}")

            filename = (
                f"guild-log/{guild_id}/{self.now.year:>04}-{self.now.month:>02}.log"
            )
            logger.debug(f"opened file: {filename!r} ({guild_id})")
            file_handle = await aiofiles.open(filename, "a")
            self.handles[guild_id] = handle = OpenFileHandle(
                file_handle, INITIAL_WRITES
            )

        handle.writes += 1
        return handle.file_handle

    def format_log(self, log: ILog, locale: str = "en-US"):
        timestamp = log.created_at.strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{timestamp}] {log.message.translate(locale)}"]

        if log.reason is not None:
            lines.append(f"Reason: {log.reason.translate(locale)}")

        if log.referenced_message is not None:
            msg = log.referenced_message
            if msg.content:
                for line in msg.content.splitlines():
                    lines.append(f">> {line}")

            lines.append(f"> Message author: {msg.author} ({msg.author.id})")
            lines.append(f"> Channel: {msg.channel_id}")
            if msg.attachments:
                lines.append("> Attachments:")
                for attachment in msg.attachments:
                    lines.append(f">> {attachment.filename} ({attachment.size} bytes)")

            if msg.stickers:
                lines.append("> Stickers:")
                for sticker in msg.stickers:
                    lines.append(f">> {sticker.name} ({sticker.id})")

        return "\n".join(lines) + "\n"

    async def on_slow_timer(self, event: SlowTimerEvent):
        now = datetime.utcnow()
        if now.year > self.now.year or now.month > self.now.month:
            # new month, reopen all handles
            await self.close_all_handles()

        else:
            for guild_id, handle in tuple(self.handles.items()):
                handle.writes //= 2
                if handle.writes == 0:
                    logger.debug(f"evicted {guild_id} because of no writes")
                    del self.handles[guild_id]
                    await handle.file_handle.close()

    async def close_all_handles(self):
        logger.info("closing all file handles")
        futures = [handle.file_handle.close() for handle in self.handles.values()]
        self.handles.clear()
        await asyncio.gather(*futures)
        logger.info("all file handles closed")
