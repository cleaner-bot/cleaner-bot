import logging
import os

from httpx import AsyncClient

from .app import TheCleanerApp
from .shared.data import GuildData
from .shared.event import IGuildEvent

logger = logging.getLogger(__name__)


class Store:
    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        secret = os.getenv("backend/proxy-secret")
        self.proxy = AsyncClient(
            base_url="https://internal-proxy.cleanerbot.xyz",
            headers={
                "referer": f"https://internal-firewall.cleanerbot.xyz/{secret}",
                "user-agent": "CleanerBot (cleanerbot.xyz 0.1.0)",
            },
        )

    def get_data(self, guild_id: int) -> GuildData | None:
        conf = self.app.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension", stacklevel=2)
            return None

        return conf.get_data(guild_id)

    def put_http(self, *items: IGuildEvent, thread_safe: bool = False):
        http = self.app.extensions.get("clend.http", None)
        if http is None:
            logger.warning("unable to find clend.http extension", stacklevel=2)
            return None

        fn = http.queue.sync_q.put if thread_safe else http.queue.async_q.put_nowait
        for item in items:
            fn(item)
