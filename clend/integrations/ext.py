import asyncio
import logging
import os
import typing

import hikari

from ..app import TheCleanerApp
from ..shared.protect import protect, protected_call
from .topgg import TopGGIntegration

logger = logging.getLogger(__name__)


class IntegrationExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    topgg: TopGGIntegration | None = None
    tasks: list[asyncio.Task]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_guild_count_change),
            (hikari.GuildLeaveEvent, self.on_guild_count_change),
        ]

        topgg_token = os.getenv("topgg/api-token")
        if topgg_token is not None:
            self.topgg = TopGGIntegration(app, topgg_token)

        self.tasks = []

    def on_load(self):
        if self.topgg is not None:
            self.tasks.append(asyncio.create_task(protect(self.topgg.vote_task)))

        asyncio.create_task(protected_call(self.update_information()))

    def on_unload(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()

    async def on_guild_count_change(
        self, event: hikari.GuildJoinEvent | hikari.GuildLeaveEvent
    ):
        await self.update_information()

    async def update_information(self):
        guild_count = len(self.app.bot.cache.get_guilds_view())
        user_count = sum(
            guild.member_count
            for guild in self.app.bot.cache.get_guilds_view().values()
        )

        logger.debug(f"stats: guilds={guild_count} users={user_count}")

        if self.topgg is not None:
            await self.topgg.update_topgg(guild_count)
