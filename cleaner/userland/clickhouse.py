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

        self.tables = defaultdict(list)
        url = os.getenv("CLICKHOUSE_URL")
        if url:
            client = AsyncClient()
            self.client = ChClient(client, url)

        self._inited = False

    def track(self, table: str, *data: typing.Any) -> None:
        if self.client is not None:
            self.tables[table].append(data)

    async def track_event(self, name: str, guild_id: int) -> None:
        timestamp = int(time.time())
        self.track("cleanerbot.events", name, timestamp, guild_id)

    async def on_init(self) -> bool:
        if not self.client or not await self.client.is_alive():
            return False

        await self.client.execute("CREATE DATABASE IF NOT EXISTS cleanerbot")
        await self.client.execute(
            "CREATE TABLE IF NOT EXISTS cleanerbot.events "
            "(event String, timestamp DateTime, guild_id UInt64) "
            "ENGINE = MergeTree() PRIMARY KEY (guild_id, timestamp)"
        )
        # await self.client.execute(
        #     "CREATE TABLE IF NOT EXISTS cleanerbot.messages "
        #     "(timestamp DateTime, ...) "
        #     "ENGINE = MergeTree() PRIMARY KEY (timestamp)"
        # )

        self._inited = True
        return True

    async def on_timer(self) -> None:
        if not self.tables or self.client is None:
            return

        if not self._inited:
            if not await self.on_init():
                logger.warning("connection to clickhouse failed")
                return

        table_copy = list(self.tables.items())
        self.tables.clear()
        for table, data in table_copy:
            logger.debug(f"pushing {len(data)} events to {table}")
            await self.client.execute("INSERT INTO cleanerbot.events VALUES", *data)
            logger.debug(f"pushed {len(data)} events to {table}")
