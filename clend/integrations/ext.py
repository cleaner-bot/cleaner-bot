import asyncio
import logging
import os
import typing

import hikari

from ..app import TheCleanerApp
from ..shared.protect import protect, protected_call
from .dlistgg import DlistGGIntegration
from .statcord import StatcordIntegration
from .topgg import TopGGIntegration

logger = logging.getLogger(__name__)


class IntegrationExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]
    topgg: TopGGIntegration | None = None
    statcord: StatcordIntegration | None = None
    dlistgg: DlistGGIntegration | None = None
    tasks: list[asyncio.Task[None]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_guild_count_change),
            (hikari.GuildLeaveEvent, self.on_guild_count_change),
        ]

        topgg_token = os.getenv("topgg/api-token")
        if topgg_token is not None:
            self.topgg = TopGGIntegration(app, topgg_token)

        dlistgg_token = os.getenv("dlistgg/api-token")
        if dlistgg_token is not None:
            self.dlistgg = DlistGGIntegration(app, dlistgg_token)

        statcord_token = os.getenv("statcord/api-token")
        if statcord_token is not None:
            self.statcord = StatcordIntegration(app, statcord_token)

        self.tasks = []

    def on_load(self) -> None:
        if self.topgg is not None:
            self.tasks.append(asyncio.create_task(protect(self.topgg.vote_task)))

        asyncio.create_task(protected_call(self.update_information()))

    def on_unload(self) -> None:
        for task in self.tasks:
            if not task.done():
                task.cancel()

    async def on_guild_count_change(
        self, event: hikari.GuildJoinEvent | hikari.GuildLeaveEvent
    ) -> None:
        await self.update_information()

    async def update_information(self) -> None:
        guild_count = len(self.app.bot.cache.get_guilds_view())
        user_count = sum(
            guild.member_count
            for guild in self.app.bot.cache.get_guilds_view().values()
            if guild.member_count
        )

        logger.debug(f"stats: guilds={guild_count} users={user_count}")

        if self.topgg is not None:
            await self.topgg.update_topgg(guild_count)

        if self.dlistgg is not None:
            await self.dlistgg.update_dlistgg(guild_count)

        if self.statcord is not None:
            await self.statcord.update_statcord(guild_count, user_count)
