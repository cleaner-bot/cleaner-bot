import asyncio
import logging
import os
import typing
from datetime import datetime
from urllib.parse import parse_qs

import hikari
import msgpack  # type: ignore
from cleaner_i18n.translate import Message
from httpx import AsyncClient

from ..app import TheCleanerApp
from ..shared.data import GuildData
from ..shared.event import ILog
from ..shared.protect import protected_call
from ..shared.sub import Message as PubMessage
from ..shared.sub import listen

logger = logging.getLogger(__name__)


class TopGGVote(typing.TypedDict):
    user: str
    type: str
    query: str
    isWeekend: bool
    bot: str


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
            if not isinstance(event, PubMessage):
                continue

            data = msgpack.unpackb(event.data)
            logger.debug(f"vote: {data}")
            asyncio.ensure_future(protected_call(self.thank_vote(data)))

    async def thank_vote(self, vote: TopGGVote):
        if not vote["query"].startswith("?"):
            return
        query = parse_qs(vote["query"][1:])
        if "guild" not in query or len(query["guild"]) != 1:
            return
        guild_id: str = query["guild"][0]

        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            return

        data = self.get_data(guild.id)
        if data is None or not data.config.logging_enabled:
            return

        user_id = int(vote["user"])
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await self.app.bot.rest.fetch_member(guild, user_id)
            except hikari.NotFoundError:
                return

        log = ILog(
            guild.id,
            Message(
                "log_vote_thankyou",
                {"user": user_id, "name": "Top.gg"},
            ),
            datetime.utcnow(),
        )
        http = self.app.extensions.get("clend.http", None)
        if http is None:
            logger.warning("tried to log http extension is not loaded")
        else:
            http.queue.async_q.put_nowait(log)

    def get_data(self, guild_id: int) -> GuildData | None:
        conf = self.app.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_data(guild_id)
