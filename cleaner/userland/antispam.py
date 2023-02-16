from __future__ import annotations

import base64
import logging
import time
import typing
from collections import defaultdict
from dataclasses import dataclass

import hikari
from expirepy import ExpiringList

from ._types import AntiSpamTriggeredEvent, ConfigType, EntitlementsType, KernelType
from .helpers.localization import Message
from .helpers.task import complain_if_none, safe_background_call
from .mitigations import mitigations, mitigationsd

logger = logging.getLogger(__name__)
ACTION_DISABLED, ACTION_BLOCK, ACTION_CHALLENGE = range(3)


@dataclass()
class ActiveMitigation:
    id: str
    name: str
    data: typing.Any
    last_triggered: float
    ttl: int


class AntispamService:
    guild_messages: dict[int, ExpiringList[hikari.Message]]
    active_mitigations: dict[int, list[ActiveMitigation]]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.bindings["antispam"] = self.message_create

        self.guild_messages = defaultdict(lambda: ExpiringList(expires=30))
        self.active_mitigations = defaultdict(list)

    async def message_create(
        self,
        message: hikari.Message,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> bool:
        assert message.guild_id is not None, "impossible"
        assert message.member is not None, "impossible"
        self.guild_messages[message.guild_id].append(message)

        active_mitigations = self.active_mitigations[message.guild_id]
        mitigation: ActiveMitigation | None = None
        info: AntiSpamTriggeredEvent
        if active_mitigations:
            mitigation = await self.check_mitigations(message, active_mitigations)
            if mitigation is not None:
                logger.debug(
                    f"antispam matched {mitigation.name} in {message.guild_id} "
                    f"id={mitigation.id} author={message.author.id}"
                )

                reason = Message(
                    "components_antispam",
                    {"mitigation": mitigation.name, "id": mitigation.id},
                )

                if delete := complain_if_none(
                    self.kernel.bindings.get("http:delete"), "http:delete"
                ):
                    await safe_background_call(
                        delete(
                            message.id,
                            message.channel_id,
                            message.author,
                            True,
                            reason,
                            message,
                        )
                    )
                if challenge := complain_if_none(
                    self.kernel.bindings.get("http:challenge"),
                    "http:challenge",
                ):
                    await safe_background_call(
                        challenge(message.member, config, True, reason, 0)
                    )

                if track := complain_if_none(
                    self.kernel.bindings.get("track"), "track"
                ):
                    info = {
                        "name": "antispam",
                        "guild_id": message.guild_id,
                        "initial": False,
                        "rule": mitigation.name,
                        "id": mitigation.id,
                    }
                    await safe_background_call(track(info))

                return True

        channel_id = str(message.channel_id)
        messages = self.guild_messages[message.guild_id].copy()
        for mit in mitigations:
            config_name = "_".join(mit.name.split(".")[1:])
            enabled = config[f"antispam_{config_name}"]  # type: ignore
            channels = config[f"antispam_{config_name}_channels"]  # type: ignore
            if not enabled or channel_id in channels:
                continue

            mitigation = mit.detection(message, messages, config)
            if mitigation is not None:
                break
        else:
            return False

        id = (
            base64.b64encode(message.id.to_bytes(8, "big"), altchars=b"  ")
            .decode()
            .replace(" ", "")
            .strip("=")
        )

        now = time.monotonic()
        active_mitigation = ActiveMitigation(id, mit.name, mitigation, now, mit.ttl)
        if mit.ttl > 0:
            active_mitigations.append(active_mitigation)

        logger.info(
            f"antispam triggered {mit.name} in {message.guild_id} id={id} "
            f"author={message.author.id}"
        )

        reason = Message("components_antispam", {"mitigation": mit.name, "id": id})

        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            await safe_background_call(log(message.guild_id, reason, None, message))

        if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
            info = {
                "name": "antispam",
                "guild_id": message.guild_id,
                "initial": True,
                "rule": mit.name,
                "id": id,
            }
            await safe_background_call(track(info))

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            await safe_background_call(
                challenge(message.member, config, True, reason, 0)
            )

        if delete := complain_if_none(
            self.kernel.bindings.get("http:delete"), "http:delete"
        ):
            for old_message in messages:
                if mit.match(active_mitigation.data, old_message):
                    await safe_background_call(
                        delete(
                            old_message.id,
                            old_message.channel_id,
                            old_message.author,
                            True,
                            reason,
                            message,
                        )
                    )

        if announcement := complain_if_none(
            self.kernel.bindings.get("http:announcement"),
            "http:announcement",
        ):
            await safe_background_call(
                announcement(
                    message.guild_id,
                    message.channel_id,
                    Message("components_antispam_announcement"),
                    0,
                )
            )

        return True

    async def check_mitigations(
        self, message: hikari.Message, active_mitigations: list[ActiveMitigation]
    ) -> ActiveMitigation | None:
        now = time.monotonic()
        for active_mitigation in active_mitigations:
            mit = mitigationsd[active_mitigation.name]
            if now - active_mitigation.last_triggered > active_mitigation.ttl:
                continue  # just ignore, it'll be cleaned up in a diff place
            if mit.match(active_mitigation.data, message):
                active_mitigation.last_triggered = now
                return active_mitigation

        return None
