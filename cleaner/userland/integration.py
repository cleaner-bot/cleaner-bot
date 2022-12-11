import asyncio
import logging
import os
import time

import psutil  # type: ignore
from httpx import AsyncClient, ReadTimeout

from ._types import KernelType
from .helpers.binding import safe_call

logger = logging.getLogger(__name__)

psutil.virtual_memory()
psutil.cpu_percent()
psutil.net_io_counters()


class IntegrationService:
    last_published: float | None = None

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["integration:timer"] = self.on_timer

        secret = os.getenv("BACKEND_PROXY_SECRET")
        self.proxy = AsyncClient(
            base_url="https://internal-proxy.cleanerbot.xyz",
            headers={
                "referer": f"https://internal-firewall.cleanerbot.xyz/{secret}",
                "user-agent": "CleanerBot (cleanerbot.xyz 0.2.0)",
            },
            timeout=30,
        )

        # setup bandwidth counters
        net_io = psutil.net_io_counters()
        self.last_bandwidth_value = net_io.bytes_recv + net_io.bytes_sent
        self.last_bandwidth_time = time.monotonic()

    async def on_timer(self) -> None:
        # prevent double posting because of reloading the consumer
        now = time.monotonic()
        if self.last_published is not None and now - self.last_published < 15 * 60:
            return
        self.last_published = now

        guild_count = 0
        while not guild_count:
            guild_count = len(self.kernel.bot.cache.get_guilds_view())
            if not guild_count:
                logger.debug(f"delaying statistics - guilds={guild_count}")
                await asyncio.sleep(5)
        user_count = sum(self.kernel.longterm["member_counts"].values())

        logger.debug(f"statistics - guilds={guild_count} users={user_count}")

        bot = self.kernel.bot.cache.get_me()
        if bot is None:
            logger.warning("unable to get bot id - cannot update!!")
            return

        await safe_call(self.update_dlistgg(bot.id, guild_count))
        await safe_call(self.update_topgg(bot.id, guild_count))
        await safe_call(self.update_statcord(bot.id, guild_count, user_count))

    async def update_dlistgg(self, bot: int, guild_count: int) -> None:
        token = os.getenv("DLIST_API_TOKEN")
        if not token:
            return

        res = await self.proxy.put(
            f"api.discordlist.gg/v0/bots/{bot}/guilds",
            params={"count": guild_count},
            headers={"authorization": f"Bearer {token}"},
        )
        res.raise_for_status()

        logger.info(f"published guild count to dlist.gg ({guild_count})")

    async def update_topgg(self, bot: int, guild_count: int) -> None:
        token = os.getenv("TOPGG_API_TOKEN")
        if not token:
            return

        res = await self.proxy.post(
            f"top.gg/api/bots/{bot}/stats",
            json={"server_count": guild_count},
            headers={"authorization": token},
        )
        res.raise_for_status()

        logger.info(f"published guild count to top.gg ({guild_count})")

    async def update_statcord(
        self, bot: int, guild_count: int, user_count: int
    ) -> None:
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        total_messages = self.kernel.longterm.get("total_messages", 0)
        data = {
            "servers": str(guild_count),
            "users": str(user_count),
            "active": [],  # hell naw, this is sensitive data
            "commands": str(total_messages),
            "popular": [],  # not applicable
            "memactive": str(memory.used),
            "memload": str(memory.percent),
            "cpuload": str(cpu_percent),
            "bandwidth": self.get_bandwidth(),
        }

        token = os.getenv("STATCORD_API_TOKEN")
        if not token:
            return

        try:
            res = await self.proxy.post(
                "api.statcord.com/v3/stats", json={"id": bot, "key": token, **data}
            )
        except ReadTimeout:
            logger.debug("statcord is down again, got a ReadTimeout")
            return

        if res.status_code == 502:
            logger.debug("statcord is down again, got a 502")
            return
        res.raise_for_status()

        logger.debug(f"published stats to statcord: {data}")

    def get_bandwidth(self) -> int:
        net_io = psutil.net_io_counters()

        total_bandwidth = net_io.bytes_sent + net_io.bytes_recv
        used_bandwidth_since_last = total_bandwidth - self.last_bandwidth_value
        now = time.monotonic()
        time_diff = now - self.last_bandwidth_time

        self.last_bandwidth_time = now
        self.last_bandwidth_value = total_bandwidth

        return round(used_bandwidth_since_last / time_diff)
