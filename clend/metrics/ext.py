import asyncio
import copy
import typing
import logging
import time

import hikari
import msgpack  # type: ignore

from .metrics import Metrics, metrics_reader
from ..bot import TheCleaner
from ..shared.protect import protect

logger = logging.getLogger(__name__)


class MetricsExtension:
    queue: asyncio.Queue[typing.Any]
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    metrics: Metrics

    def __init__(self, bot: TheCleaner) -> None:
        super().__init__()
        self.bot = bot
        self.listeners = []
        self.queue = asyncio.Queue()
        self.task = None
        self.metrics = Metrics()

    def on_load(self):
        self.task = asyncio.create_task(protect(self.maind))

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

        self.metrics.flush()
        self.metrics.close()

    async def maind(self):
        loop = asyncio.get_running_loop()

        if not self.metrics.history:
            temp_storage = []
            loading = loop.run_in_executor(None, self.load_metrics)
            while not loading.done():
                temp_storage.append(await self.queue.get())
            logger.info("all metrics loaded")

            for event in temp_storage:
                logger.debug(event)
                self.metrics.log(event)

        last_update = None
        while True:
            now = time.monotonic()
            if last_update is None or now - last_update > 300:
                logger.debug("updating radar")
                await loop.run_in_executor(None, self.metrics.flush)
                data, guilds = await loop.run_in_executor(None, self.gather_radar_data)
                await self.bot.database.set("radar", data)
                for guild_id, guild_data in guilds.items():
                    await self.bot.database.set(f"guild:{guild_id}:radar", guild_data)
                last_update = now
                logger.debug("radar updated")

            event = await self.queue.get()
            logger.debug(event)
            self.metrics.log(event)

    def load_metrics(self):
        logger.debug("loading metrics.bin")
        self.metrics.history = list(metrics_reader())
        logger.debug("loaded metrics.bin")

    def gather_radar_data(self):
        phishing_rules = (
            "phishing.content",
            "phishing.domain.blacklisted",
            "phishing.domain.heuristic",
            "phishing.embed",
        )
        ping = (
            "ping.users.many",
            "ping.users.few",
            "ping.roles",
            "ping.broad",
            "ping.hidden",
        )
        advertisement = ("advertisement.discord.invite",)
        other = ("selfbot.embed", "emoji.mass")
        all_rules = phishing_rules + ping + advertisement + other

        traffic = (
            "traffic.similar",
            "traffic.exact",
            "traffic.token",
            "traffic.sticker",
            "traffic.attachment",
        )

        challenge_actions = ("ban", "kick", "role", "timeout", "failure")
        categories = ("phishing", "antispam", "advertisement", "other")

        timespan = 60 * 60 * 24 * 30
        latest = self.metrics.history[-1][0]
        cutoff_now = latest - timespan
        cutoff_previous = latest - timespan * 2

        result = {
            "rules": {r: {"previous": 0, "now": 0} for r in all_rules},
            "traffic": {t: {"previous": 0, "now": 0} for t in traffic},
            "categories": {c: {"previous": 0, "now": 0} for c in categories},
            "challenges": {c: {"previous": 0, "now": 0} for c in challenge_actions},
            "stats": {
                "guild_count": len(self.bot.bot.cache.get_guilds_view()),
                "user_count": len(self.bot.bot.cache.get_users_view()),
            },
        }
        guild_template = {
            "rules": {r: {"previous": 0, "now": 0} for r in all_rules},
            "traffic": {t: {"previous": 0, "now": 0} for t in traffic},
            "categories": {c: {"previous": 0, "now": 0} for c in categories},
            "challenges": {c: {"previous": 0, "now": 0} for c in challenge_actions},
        }
        guilds = {}

        for timestamp, data in self.metrics.history:
            if data["guild"] not in guilds:
                guilds[data["guild"]] = copy.deepcopy(guild_template)
            if cutoff_previous > timestamp:  # too old
                continue
            span = "previous" if cutoff_now > timestamp else "now"
            guild = guilds[data["guild"]]
            if data["name"] == "challenge":
                result["challenges"][data["action"]][span] += 1
                guild["challenges"][data["action"]][span] += 1
            elif data["name"] == "delete":
                rule = data["info"]["rule"]
                category = None
                if rule in all_rules:
                    result["rules"][rule][span] += 1
                    guild["rules"][rule][span] += 1
                    if rule in phishing_rules:
                        category = "phishing"
                    elif rule in advertisement:
                        category = "advertisement"
                    else:
                        category = "other"
                elif rule in traffic:
                    result["traffic"][rule][span] += 1
                    guild["traffic"][rule][span] += 1
                    category = "antispam"
                else:
                    logger.warning(f"unknown rule: {rule}")

                if category is not None:
                    result["categories"][category][span] += 1
                    guild["categories"][category][span] += 1

        return msgpack.packb(result), {
            guild_id: msgpack.packb(guild_data)
            for guild_id, guild_data in guilds.items()
        }
