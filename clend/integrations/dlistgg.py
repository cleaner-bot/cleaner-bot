import logging

from ..app import TheCleanerApp

logger = logging.getLogger(__name__)


class DlistGGIntegration:
    def __init__(self, app: TheCleanerApp, dlistgg_token: str) -> None:
        self.app = app
        self.dlistgg_token = dlistgg_token

    async def update_dlistgg(self, guild_count: int) -> None:
        bot_id = str(self.app.store.ensure_bot_id())

        res = await self.app.store.proxy.put(
            f"api.discordlist.gg/v0/bots/{bot_id}/guilds",
            params={"count": guild_count},
            headers={"authorization": f"Bearer {self.dlistgg_token}"},
        )
        if res.status_code == 429:
            logger.debug(
                "failed to publish guild count to dlist.gg because harry "
                "put harsh ratelimits"
            )
            return  # fuck you Harry
        res.raise_for_status()

        logger.info(f"published guild count to dlist.gg: {guild_count}")
