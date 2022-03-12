import logging
import time
import typing
import queue

from cleaner_conf.guild.config import Config
from cleaner_conf.guild.entitlements import Entitlements
from expirepy import ExpiringList, ExpiringSum

from ..bot import TheCleaner
from ..shared.event import IGuildEvent


logger = logging.getLogger(__name__)


class CleanerGuild:
    event_queue: queue.Queue[IGuildEvent]
    active_mitigations: list[typing.Any]

    def __init__(self, guild_id: int, bot: TheCleaner) -> None:
        self.id = guild_id
        self.bot = bot

        # config and entitlements arent available immediately
        self.settings_loaded = False
        self.event_queue = queue.Queue()

        # cache and stuff
        self.messages = ExpiringList(expires=30)
        self.member_joins = ExpiringSum(expires=300)
        self.active_mitigations = []

    def evict_cache(self):
        self.messages.evict()
        self.member_joins.evict()

        now = time.monotonic()
        for mitigation in tuple(self.active_mitigations):
            if now - mitigation.last_triggered > mitigation.ttl:  # expired
                self.active_mitigations.remove(mitigation)

    def get_config(self) -> Config | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None
        return conf.get_config(self.id)

    def get_entitlements(self) -> Entitlements | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None
        return conf.get_entitlements(self.id)
