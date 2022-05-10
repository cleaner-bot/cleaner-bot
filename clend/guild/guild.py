from __future__ import annotations

import logging
import queue
import time
import typing

import hikari
import lupa  # type: ignore
from expirepy import ExpiringList, ExpiringSet

from ..app import TheCleanerApp
from ..shared.data import GuildData

logger = logging.getLogger(__name__)


class CleanerGuild:
    event_queue: queue.Queue[hikari.Event]
    worker: tuple[lupa.LuaRuntime, typing.Any] | None
    worker_spec: typing.Any

    messages: ExpiringList[hikari.Message]
    message_count: dict[int, list[int]]
    pending_message_count: dict[int, int]
    current_slowmode: dict[int, int]
    member_joins: ExpiringSet[hikari.Snowflake]
    member_kicks: ExpiringSet[hikari.Snowflake]
    active_mitigations: list[typing.Any]
    verification_joins: dict[int, float]

    def __init__(self, guild_id: int, app: TheCleanerApp) -> None:
        self.id = guild_id
        self.app = app

        # config and entitlements arent available immediately
        self.settings_loaded = False
        self.event_queue = queue.Queue()
        self.worker = None
        self.worker_spec = None

        # cache and stuff
        self.messages = ExpiringList(expires=30)
        self.message_count = {}
        self.pending_message_count = {}
        self.current_slowmode = {}
        self.member_joins = ExpiringSet(expires=300)
        self.member_kicks = ExpiringSet(expires=300)
        self.active_mitigations = []
        self.verification_joins = {}  # no cache evict needed

    def evict_cache(self):
        self.messages.evict()
        self.member_joins.evict()

        now = time.monotonic()
        for mitigation in tuple(self.active_mitigations):
            if now - mitigation.last_triggered > mitigation.ttl:  # expired
                self.active_mitigations.remove(mitigation)

    def get_data(self) -> GuildData | None:
        conf = self.app.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_data(self.id)
