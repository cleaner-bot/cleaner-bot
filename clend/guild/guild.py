import logging
import time
import typing
import queue

import hikari

from cleaner_conf.guild import GuildConfig, GuildEntitlements
from expirepy import ExpiringList, ExpiringCounter

from ..bot import TheCleaner


logger = logging.getLogger(__name__)


class CleanerGuild:
    event_queue: queue.Queue[hikari.Event]
    active_mitigations: list[typing.Any]
    message_count: dict[int, ExpiringCounter]
    current_slowmode: dict[int, int]
    verification_joins: dict[int, float]

    def __init__(self, guild_id: int, bot: TheCleaner) -> None:
        self.id = guild_id
        self.bot = bot

        # config and entitlements arent available immediately
        self.settings_loaded = False
        self.event_queue = queue.Queue()

        # cache and stuff
        self.messages = ExpiringList(expires=30)
        self.message_count = {}
        self.current_slowmode = {}
        self.member_joins = ExpiringCounter(expires=300)
        self.active_mitigations = []
        self.verification_joins = {}  # no cache evict needed

    def evict_cache(self):
        self.messages.evict()
        self.member_joins.evict()

        now = time.monotonic()
        for mitigation in tuple(self.active_mitigations):
            if now - mitigation.last_triggered > mitigation.ttl:  # expired
                self.active_mitigations.remove(mitigation)

    def get_config(self) -> GuildConfig | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None
        return conf.get_config(self.id)

    def get_entitlements(self) -> GuildEntitlements | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None
        return conf.get_entitlements(self.id)
