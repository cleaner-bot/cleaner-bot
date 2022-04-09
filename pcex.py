import asyncio
import logging

import hikari
from hikari.impl import event_manager

logger = logging.getLogger(__name__)


async def noop(*dev, **null):
    pass


class PatchChunkingCPUExhaustion:
    def __init__(self, bot: hikari.GatewayBot) -> None:
        self.bot = bot
        self.lock = asyncio.Lock()

    async def on_guild_available(self, ev: hikari.GuildAvailableEvent):
        if not ev.guild.is_large:
            return
        logger.debug(f"entering queue {ev.guild_id}")
        async with self.lock:
            logger.debug(f"requesting members {ev.guild_id}")
            await self.bot.request_guild_members(ev.guild)
            await asyncio.sleep(3)
            logger.debug(f"got members {ev.guild_id}")


def inject(bot: hikari.GatewayBot):
    event_manager._request_guild_members = noop
    pcex = PatchChunkingCPUExhaustion(bot)
    bot.listen(hikari.GuildAvailableEvent)(pcex.on_guild_available)
