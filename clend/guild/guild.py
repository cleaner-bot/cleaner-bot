import time
import typing
import queue

from cleaner_conf import Config, Entitlements
from expirepy import ExpiringList, ExpiringSum

from ..shared.event import IGuildEvent


class CleanerGuild:
    event_queue: queue.Queue[IGuildEvent]
    active_mitigations: list[typing.Any]

    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        # settings
        self.config = Config()
        self.entitlements = Entitlements()

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
