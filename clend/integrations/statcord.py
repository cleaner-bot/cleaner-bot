import logging

from ..app import TheCleanerApp

logger = logging.getLogger(__name__)


class StatcordIntegration:
    def __init__(self, app: TheCleanerApp, statcord_token: str) -> None:
        self.app = app
        self.statcord_token = statcord_token

    async def update_statcord(self, guild_count: int, user_count: int) -> None:
        me = self.app.bot.cache.get_me()
        if me is None:
            # dont bother handling because this should NEVER happen
            raise RuntimeError("no bot id available")

        bot_id = str(me.id)
        event = self.prepare_event(guild_count, user_count)

        res = await self.app.store.proxy.post(
            "api.statcord.com/v3/stats",
            json={"id": bot_id, "key": self.statcord_token, **event},
        )
        res.raise_for_status()

        logger.debug(f"published stats to statcord: {event}")

    def prepare_event(
        self, guild_count: int, user_count: int
    ) -> dict[str, str | list[str]]:
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
