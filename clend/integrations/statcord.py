import asyncio
import logging

from httpx import HTTPStatusError

from ..app import TheCleanerApp

logger = logging.getLogger(__name__)


class StatcordIntegration:
    def __init__(self, app: TheCleanerApp, statcord_token: str) -> None:
        self.app = app
        self.statcord_token = statcord_token

    async def update_task(self):
        while True:
            try:
                await self.update_statcord()
            except HTTPStatusError as e:
                logger.exception(e.response.text, exc_info=e)
            await asyncio.sleep(60)

    async def update_statcord(self):
        me = self.app.bot.cache.get_me()
        if me is None:
            # dont bother handling because this should NEVER happen
            raise RuntimeError("no bot id available")

        bot_id = str(me.id)
        event = self.prepare_event()

        res = await self.app.store.proxy.post(
            "api.statcord.com/v3/stats",
            json={"id": bot_id, "key": self.statcord_token, **event},
        )
        res.raise_for_status()

        logger.debug(f"published stats to statcord: {event}")

    def prepare_event(self) -> dict[str, str]:
        guild_count = len(self.app.bot.cache.get_guilds_view())
        user_count = sum(
            guild.member_count  # type: ignore
            for guild in self.app.bot.cache.get_guilds_view().values()
        )

        return {
            "servers": str(guild_count),
            "users": str(user_count),
            "active": [],
            "commands": "0",
            "popular": [],
            "memactive": "0",
            "memload": "0",
            "cpuload": "0",
            "bandwidth": "0",
        }
