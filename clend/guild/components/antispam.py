import base64
from dataclasses import dataclass
import logging
import time
import typing

import hikari

from .mitigations import mitigations, mitigationsd
from ..guild import CleanerGuild
from ..helper import action_delete, action_challenge, announcement, is_moderator
from ...shared.event import IGuildEvent


logger = logging.getLogger(__name__)


@dataclass()
class ActiveMitigation:
    id: str
    name: str
    data: typing.Any
    last_triggered: float
    ttl: int


def on_message_create(event: hikari.GuildMessageCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if event.member is None or is_moderator(guild, event.member) or config is None:
        return
    messages: list[hikari.Message] = guild.messages.copy()
    guild.messages.append(event.message)

    now = time.monotonic()

    active_mitigation: ActiveMitigation
    for active_mitigation in guild.active_mitigations:
        mit = mitigationsd[active_mitigation.name]
        if now - active_mitigation.last_triggered > active_mitigation.ttl:
            continue  # just ignore, it'll be cleaned up in a diff place
        if mit.match(active_mitigation.data, event.message):
            name = f"antispam {active_mitigation.name} {active_mitigation.id}"
            active_mitigation.last_triggered = now
            return [
                action_delete(
                    event.member,
                    event.message,
                    name,
                ),
                action_challenge(
                    guild,
                    event.member,
                    name,
                    block=True,
                ),
            ]

    mitigation = None
    for mit in mitigations:
        config_name = "_".join(mit.name.split(".")[1:])
        enabled = getattr(config, f"antispam_{config_name}")
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

    name = f"antispam {active_mitigation.name} {active_mitigation.id}"
    actions: list[IGuildEvent] = []
    for old_message in messages:
        if mit.match(mitigation, old_message):
            if old_message.member is None:
                logger.warning("encountered an old message without member")
            else:
                actions.append(action_delete(old_message.member, old_message, name))

    actions.append(action_delete(event.member, event.message, name))
    actions.append(action_challenge(guild, event.member, name, block=True))
    if mit.ttl > 0:
        channel = event.get_channel()
        if channel is not None:
            actions.append(
                announcement(channel, f"mitigation.announcement.{mit.name}", mit.ttl)
            )

    return actions


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
]
