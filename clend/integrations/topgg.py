import logging
import os

import msgpack  # type: ignore
from httpx import AsyncClient

from ..app import TheCleanerApp
from ..shared.sub import Message, listen

logger = logging.getLogger(__name__)


class TopGGIntegration:
    client: AsyncClient

    def __init__(self, app: TheCleanerApp, topgg_token: str) -> None:
        self.app = app
        self.topgg = AsyncClient(
            base_url="https://top.gg/",
            headers={
                "authorization": topgg_token,
                "user-agent": "CleanerBot (cleanerbot.xyz 0.1.0)",
            },
        )

    async def update_topgg(self, guild_count: int):
        client_id = os.getenv("discord/client-id")
        if client_id is None:
            me = self.app.bot.cache.get_me()
            if me is None:
                # dont bother handling because this should NEVER happen
                raise RuntimeError("no client_id available")

            client_id = str(me.id)

        res = await self.topgg.post(
            f"/api/bots/{client_id}/stats", json={"server_count": guild_count}
        )
        res.raise_for_status()

        logger.info(f"published guild count to top.gg: {guild_count}")

    async def vote_task(self):
        pubsub = self.app.database.pubsub()
        await pubsub.subscribe("pubsub:integrations:topgg-vote")
        async for event in listen(pubsub):
            if not isinstance(event, Message):
                continue

            data = msgpack.unpackb(event.data)
            logger.debug(f"vote: {data}")
