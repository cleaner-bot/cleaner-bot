import asyncio
import logging
import typing
from datetime import datetime
from urllib.parse import parse_qs

import hikari
import msgpack  # type: ignore
from cleaner_i18n import Message

from ..app import TheCleanerApp
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
    def __init__(self, app: TheCleanerApp, topgg_token: str) -> None:
        self.app = app
        self.topgg_token = topgg_token

    async def update_topgg(self, guild_count: int) -> None:
        me = self.app.bot.cache.get_me()
        if me is None:
            # dont bother handling because this should NEVER happen
            raise RuntimeError("no bot id available")

        bot_id = str(me.id)

        res = await self.app.store.proxy.post(
            f"top.gg/api/bots/{bot_id}/stats",
            json={"server_count": guild_count},
            headers={"authorization": self.topgg_token},
        )
        res.raise_for_status()

        logger.info(f"published guild count to top.gg: {guild_count}")

    async def vote_task(self) -> None:
        pubsub = self.app.database.pubsub()
        await pubsub.subscribe("pubsub:integrations:topgg-vote")
        async for event in listen(pubsub):
            if not isinstance(event, PubMessage):
                continue

            data = msgpack.unpackb(event.data)
            logger.debug(f"vote: {data}")
            asyncio.ensure_future(protected_call(self.thank_vote(data)))

    async def thank_vote(self, vote: TopGGVote) -> None:
        if not vote["query"].startswith("?"):
            return
        query = parse_qs(vote["query"][1:])
        if "guild" not in query or len(query["guild"]) != 1:
            return
        guild_id: str = query["guild"][0]

        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            return

        data = self.app.store.get_data(guild.id)
        if data is None or not data.config.logging_enabled:
            return

        user_id = int(vote["user"])
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await self.app.bot.rest.fetch_member(guild, user_id)
            except hikari.NotFoundError:
                return

        for role in member.get_roles():
            if role.permissions & (
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD
            ):
                break
        else:
            return

        log = ILog(
            guild.id,
            Message(
                "log_vote_thankyou",
                {"user": user_id, "name": "Top.gg"},
            ),
            datetime.utcnow(),
        )
        self.app.store.put_http(log)
