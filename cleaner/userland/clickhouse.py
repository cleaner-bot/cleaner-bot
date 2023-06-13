import logging
import os
import time
import typing
from collections import defaultdict

from aiochclient.client import ChClient  # type: ignore
from httpx import AsyncClient

from ._types import KernelType

logger = logging.getLogger(__name__)


class ClickHouseService:
    client: ChClient | None = None
    tables: dict[str, list[tuple[typing.Any, ...]]]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.bindings["clickhouse:timer"] = self.on_timer
        self.kernel.bindings["clickhouse:track:event"] = self.track_event
        self.kernel.bindings["clickhouse:track:stats"] = self.track_stats
        self.kernel.bindings["clickhouse:track:message"] = self.track_messsage

        self.tables = defaultdict(list)
        url = os.getenv("CLICKHOUSE_URL")
        if url:
            client = AsyncClient()
            logger.info(f"clickhouse url: {url}")
            self.client = ChClient(client, url)

        self._inited = False

    def track(self, table: str, *data: typing.Any) -> None:
        if self.client is not None:
            self.tables[table].append(data)

    async def track_event(self, name: str, guild_id: int) -> None:
        timestamp = int(time.time())
        self.track("cleanerbot.events", name, timestamp, int(guild_id))

    async def track_stats(
        self, guild_count: int, user_count: int, users_cache: int, members_cache: int
    ) -> None:
        timestamp = int(time.time())
        self.track(
            "cleanerbot.stats",
            guild_count,
            user_count,
            users_cache,
            members_cache,
            timestamp,
        )

    async def track_members(self) -> None:
        if "member_counts" not in self.kernel.longterm:
            return
        timestamp = int(time.time())
        for guild_id, members in self.kernel.longterm["member_counts"].items():
            self.track("cleanerbot.members", (guild_id, members, timestamp))

    async def track_messsage(
        self, message_id: int, is_bad: bool, params: list[int]
    ) -> None:
        self.track("cleanerbot.messages", message_id, is_bad, params)

    async def on_init(self) -> bool:
        if not self.client or not await self.client.is_alive():
            return False

        await self.client.execute("CREATE DATABASE IF NOT EXISTS cleanerbot")
        await self.client.execute(
            "CREATE TABLE IF NOT EXISTS cleanerbot.events "
            "(event String, timestamp DateTime, guild_id UInt64) "
            "ENGINE = MergeTree() PRIMARY KEY (guild_id, timestamp)"
        )
        await self.client.execute(
            "CREATE TABLE IF NOT EXISTS cleanerbot.stats "
            "(guilds UInt32, users UInt32, users_cache UInt32,"
            " members_cache UInt32, timestamp DateTime) "
            "ENGINE = MergeTree() PRIMARY KEY (timestamp)"
        )
        await self.client.execute(
            "CREATE TABLE IF NOT EXISTS cleanerbot.members "
            "(guild_id UInt64, users UInt32, timestamp DateTime) "
            "ENGINE = MergeTree() PRIMARY KEY (guild_id, timestamp)"
        )
        await self.client.execute(
            "CREATE TABLE IF NOT EXISTS cleanerbot.messages "
            "(messageId UInt64, isBad Boolean, params Array(UInt16)) "
            "ENGINE = MergeTree() PRIMARY KEY (messageId)"
        )

        self._inited = True
        return True

    async def on_timer(self) -> None:
        if not self.tables or self.client is None:
            return

        if not self._inited and not await self.on_init():
            logger.warning("connection to clickhouse failed")
            return

        await self.track_members()

        table_copy = list(self.tables.items())
        self.tables.clear()
        for table, data in table_copy:
            logger.debug(f"pushing {len(data)} events to {table}")
            await self.client.execute(f"INSERT INTO {table} VALUES", *data)
            logger.debug(f"pushed {len(data)} events to {table}")
