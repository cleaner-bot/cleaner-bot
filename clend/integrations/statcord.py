import logging
import time

import psutil  # type: ignore

from ..app import TheCleanerApp

logger = logging.getLogger(__name__)


class StatcordIntegration:
    def __init__(self, app: TheCleanerApp, statcord_token: str) -> None:
        self.app = app
        self.statcord_token = statcord_token

        # need to call these once so we get accurate numbers later on
        psutil.virtual_memory()
        psutil.cpu_percent()

        net_io = psutil.net_io_counters()
        self.last_bandwidth_value = net_io.bytes_recv + net_io.bytes_sent
        self.last_bandwidth_time = time.monotonic()

    async def update_statcord(self, guild_count: int, user_count: int) -> None:
        bot_id = str(self.app.store.ensure_bot_id())
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
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent()
        net_io = psutil.net_io_counters()

        new_bandwidth = (
            net_io.bytes_sent + net_io.bytes_recv - self.last_bandwidth_value
        )
        now = time.monotonic()
        time_diff = now - self.last_bandwidth_time

        self.last_bandwidth_value = net_io.bytes_sent + net_io.bytes_recv
        self.last_bandwidth_time = now
        return {
            "servers": str(guild_count),
            "users": str(user_count),
            "active": [],
            "commands": "0",
            "popular": [],
            "memactive": str(memory.used),
            "memload": str(memory.percent),
            "cpuload": str(cpu_percent),
            "bandwidth": str(round(new_bandwidth / time_diff)),
        }
