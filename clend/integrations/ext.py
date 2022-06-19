import asyncio
import logging
import os
import time
import typing

import hikari

from ..app import TheCleanerApp
from ..shared.protect import protect
from .dlistgg import DlistGGIntegration
from .statcord import StatcordIntegration
from .topgg import TopGGIntegration

logger = logging.getLogger(__name__)
MIN_PUBLISH_DELAY = 600


class IntegrationExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]
    topgg: TopGGIntegration | None = None
    statcord: StatcordIntegration | None = None
    dlistgg: DlistGGIntegration | None = None
    tasks: list[asyncio.Task[None]]
    member_counts: dict[int, int]

    last_published: float | None = 0
    last_guilds: int | None = None
    last_users: int | None = None

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = [
            (hikari.GuildJoinEvent, self.on_guild_count_change),
            (hikari.GuildLeaveEvent, self.on_guild_count_change),
            (hikari.MemberCreateEvent, self.on_member_create),
            (hikari.MemberDeleteEvent, self.on_member_delete),
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
        self.member_counts = {}

    def on_load(self) -> None:
        self.tasks.append(asyncio.create_task(protect(self.update_task)))
        if self.topgg is not None:
            self.tasks.append(asyncio.create_task(protect(self.topgg.vote_task)))

        for guild in self.app.bot.cache.get_guilds_view().values():
            if guild.member_count:
                self.member_counts[guild.id] = guild.member_count

    def on_unload(self) -> None:
        for task in self.tasks:
            if not task.done():
                task.cancel()

    async def update_task(self) -> None:
        await asyncio.sleep(10)
        while True:
            await self.update_information()
            await asyncio.sleep(1800)

    async def on_guild_count_change(
        self, event: hikari.GuildJoinEvent | hikari.GuildLeaveEvent
    ) -> None:
        if isinstance(event, hikari.GuildJoinEvent):
            if event.guild.member_count:
                self.member_counts[event.guild_id] = event.guild.member_count

        elif event.guild_id in self.member_counts:
            del self.member_counts[event.guild_id]

        await self.update_information()

    async def on_member_create(self, event: hikari.MemberCreateEvent) -> None:
        if event.guild_id in self.member_counts:
            self.member_counts[event.guild_id] += 1
        else:
            self.member_counts[event.guild_id] = 1

    async def on_member_delete(self, event: hikari.MemberDeleteEvent) -> None:
        if event.guild_id in self.member_counts:
            self.member_counts[event.guild_id] -= 1
        else:
            self.member_counts[event.guild_id] = 0

    async def update_information(self) -> None:
        now = time.monotonic()
        if (
            self.last_published is not None
            and now - self.last_published < MIN_PUBLISH_DELAY
        ):
            return
        self.last_published = now

        guild_count = len(self.app.bot.cache.get_guilds_view())
        user_count = sum(self.member_counts.values())

        should_update_guild = self.last_guilds != guild_count
        # should_update_users = self.last_users != user_count
        self.last_guilds = guild_count
        self.last_users = user_count

        logger.debug(f"stats: guilds={guild_count} users={user_count}")

        if self.topgg is not None and should_update_guild:
            await self.topgg.update_topgg(guild_count)

        if self.dlistgg is not None and should_update_guild:
            await self.dlistgg.update_dlistgg(guild_count)

        if self.statcord is not None:
            await self.statcord.update_statcord(guild_count, user_count)
