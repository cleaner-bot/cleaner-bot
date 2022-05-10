import base64
import logging
import time
import typing
from dataclasses import dataclass

import hikari
from cleaner_i18n.translate import Message

from ...shared.custom_events import SlowTimerEvent
from ...shared.event import IGuildEvent, ILog
from ..guild import CleanerGuild
from ..helper import action_challenge, action_delete, announcement, is_moderator
from .mitigations import mitigations, mitigationsd

logger = logging.getLogger(__name__)


@dataclass()
class ActiveMitigation:
    id: str
    name: str
    data: typing.Any
    last_triggered: float
    ttl: int


def on_message_create(event: hikari.GuildMessageCreateEvent, guild: CleanerGuild):
    data = guild.get_data()
    if event.member is None or is_moderator(guild, event.member) or data is None:
        return
    messages: typing.Sequence[hikari.Message] = guild.messages.copy()
    guild.messages.append(event.message)

    now = time.monotonic()

    active_mitigation: ActiveMitigation
    for active_mitigation in guild.active_mitigations:
        mit = mitigationsd[active_mitigation.name]
        if now - active_mitigation.last_triggered > active_mitigation.ttl:
            continue  # just ignore, it'll be cleaned up in a diff place
        if mit.match(active_mitigation.data, event.message):
            reason = Message("components_antispam", {"mitigation": mit.name})
            info = {
                "name": "antispam",
                "initial": False,
                "rule": mit.name,
            }
            active_mitigation.last_triggered = now
            return [
                action_delete(
                    event.member,
                    event.message,
                    reason=reason,
                    info=info,
                ),
                action_challenge(
                    guild,
                    event.member,
                    block=mit.block,
                    reason=reason,
                    info=info,
                ),
            ]

    mitigation = None
    for mit in mitigations:
        config_name = "_".join(mit.name.split(".")[1:])
        enabled = getattr(data.config, f"antispam_{config_name}")
        if not enabled:
            continue

        mitigation = mit.detection(event.message, messages, guild)
        if mitigation is not None:
            break
    else:
        return

    id = (
        base64.b64encode(
            event.message_id.to_bytes(8, "big").lstrip(b"\x00"), altchars=b"  "
        )
        .decode()
        .replace(" ", "")
        .strip("=")
    )

    active_mitigation = ActiveMitigation(id, mit.name, mitigation, now, mit.ttl)
    if mit.ttl > 0:
        guild.active_mitigations.append(active_mitigation)

    reason = Message("components_antispam", {"mitigation": mit.name})
    info = {
        "name": "antispam",
        "initial": True,
        "rule": mit.name,
        "mit_data": mitigation,
    }
    actions: list[IGuildEvent] = []
    actions.append(ILog(event.guild_id, reason, event.message_id.created_at))
    for old_message in messages:
        if mit.match(mitigation, old_message):
            if old_message.member is None:
                logger.warning("encountered an old message without member")
            else:
                actions.append(
                    action_delete(
                        old_message.member, old_message, reason=reason, info=info
                    )
                )

    actions.append(action_delete(event.member, event.message, reason=reason, info=info))
    actions.append(
        action_challenge(guild, event.member, block=mit.block, reason=reason, info=info)
    )
    if mit.ttl > 0:
        channel = event.get_channel()
        if channel is not None:
            actions.append(
                announcement(
                    channel,
                    Message("components_antispam_announcement", {}),
                    mit.ttl,
                )
            )

    return actions


def on_slow_timer(event: SlowTimerEvent, guild: CleanerGuild):
    now = time.monotonic()
    active_mitigations: list[ActiveMitigation] = guild.active_mitigations

    guild.messages.evict()
    guild.active_mitigations = [
        x for x in active_mitigations if now - x.last_triggered <= x.ttl
    ]


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
    (SlowTimerEvent, on_slow_timer),
]
