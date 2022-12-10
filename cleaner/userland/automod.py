from __future__ import annotations

import logging

import hikari

from ._types import AutoModTriggeredEvent, ConfigType, EntitlementsType, KernelType
from .helpers.binding import complain_if_none, safe_call
from .helpers.localization import Message
from .helpers.url import has_url
from .rules import automod_rules

logger = logging.getLogger(__name__)
ACTION_DISABLED, ACTION_BLOCK, ACTION_CHALLENGE = range(3)


class AutoModService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.bindings["automod"] = self.analyze_message

    async def analyze_message(
        self,
        message: hikari.PartialMessage,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> bool:
        assert message.member, "impossible"
        assert message.guild_id

        matched_rule: str | None = None
        matched_action: int = ACTION_DISABLED
        channel_id = str(message.channel_id)

        for rule in automod_rules:
            config_name = rule.name.replace(".", "_")
            action = config[f"rules_{config_name}"]  # type: ignore
            if (
                action <= matched_action
                or channel_id in config[f"rules_{config_name}_channels"]  # type: ignore
            ):
                continue

            if rule.func(self.kernel, message):
                matched_rule = rule.name
                matched_action = action
                if action == ACTION_CHALLENGE:  # short circuit
                    break

        if matched_rule is None:
            return False

        logger.debug(
            f"author={message.member.user} ({message.member.id}) "
            f"rule={matched_rule} action={matched_action}"
        )

        reason = Message("components_automod", {"rule": matched_rule})

        if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
            info: AutoModTriggeredEvent = {
                "name": "automod",
                "guild_id": message.member.guild_id,
                "rule": matched_rule,
            }
            await safe_call(track(info), True)

        if delete := complain_if_none(
            self.kernel.bindings.get("http:delete"), "http:delete"
        ):
            await safe_call(
                delete(
                    message.id,
                    message.channel_id,
                    message.member.user,
                    True,
                    reason,
                    message,
                ),
                True,
            )

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            await safe_call(
                challenge(
                    message.member,
                    config,
                    matched_action == ACTION_BLOCK,
                    reason,
                    0,
                ),
                True,
            )

        if announcement := complain_if_none(
            self.kernel.bindings.get("http:announcement"),
            "http:announcement",
        ):
            announcement_message = Message(
                f"components_automod_{matched_rule.replace('.', '_')}",
                {"user": message.member.id},
            )

            await safe_call(
                announcement(
                    message.guild_id, message.channel_id, announcement_message, 20
                ),
                True,
            )

        if (
            (matched_rule.startswith("phishing.") or matched_rule == "ping.broad")
            and message.content
            and isinstance(message, hikari.Message)
            and has_url(message.content)
            and "discord.gg" not in message.content
        ):
            if radar_phishing_submit := complain_if_none(
                self.kernel.bindings.get("radar:phishing:submit"),
                "radar:phishing:submit",
            ):
                await safe_call(radar_phishing_submit(message, matched_rule), True)

        if matched_rule.startswith("advertisement.discord.") and isinstance(
            message, hikari.Message
        ):
            if radar_unsafeinvite_submit := complain_if_none(
                self.kernel.bindings.get("radar:unsafeinvite:submit"),
                "radar:unsafeinvite:submit",
            ):
                await safe_call(radar_unsafeinvite_submit(message), True)

        return True
