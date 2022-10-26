import logging
import typing

import hikari
from decancer_py import contains, parse
from hikari.internal.time import utc_datetime

from ._types import ConfigType, EntitlementsType, KernelType, NameTriggeredEvent
from .helpers.binding import complain_if_none, safe_call
from .helpers.localization import Message

logger = logging.getLogger(__name__)


class NameService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["name:create"] = self.analyze_member
        self.kernel.bindings["name:update"] = self.member_update

    async def member_update(
        self,
        event: hikari.MemberUpdateEvent,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> bool:
        if (
            event.old_member is None
            or event.old_member.username == event.member.username
        ) and (utc_datetime() - event.member.joined_at).total_seconds() < 5:
            return False
        return await self.analyze_member(event.member, config, entitlements)

    async def analyze_member(
        self, member: hikari.Member, config: ConfigType, entitlements: EntitlementsType
    ) -> bool:
        detection: typing.Literal["discord", "custom", None] = None
        reason: Message | None = None

        if (
            config["name_discord_enabled"]
            and (
                self.is_name_blacklisted(member.username)
                or member.avatar_hash
                in self.kernel.data["discord_impersonation_avatars"]
            )
            and (member.avatar_hash is None or not member.avatar_hash.startswith("a_"))
            and (utc_datetime() - member.created_at).days < 180
        ):
            detection = "discord"
            reason = Message("components_name_discord")

        if (
            entitlements["name_advanced"] <= entitlements["plan"]
            and config["name_advanced_enabled"]
            and self.is_custom_blacklist(
                member.display_name, config["name_advanced_words"]
            )
        ):
            detection = "custom"
            reason = Message("components_name_blacklist")

        if detection is None or reason is None:
            return False

        logger.debug(
            f"name checker triggered (user={member.id} guild={member.guild_id} "
            f"display_name={member.display_name})"
        )

        if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
            info: NameTriggeredEvent = {
                "name": "name",
                "guild_id": member.guild_id,
                "detection": detection,
                "id": member.id,
            }
            await safe_call(track(info), True)

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            await safe_call(challenge(member, config, True, reason, 1), True)

        return True

    def is_name_blacklisted(self, name: str) -> bool:
        parts = set(parse(name).split())
        blacklisted = set(self.kernel.data["discord_impersonation_names"])
        return not bool(parts - blacklisted)

    def is_custom_blacklist(self, name: str, words: list[str]) -> bool:
        name = parse(name)
        split_name = name.split()
        for word in words:
            any_start = word.startswith("*")
            any_end = word.endswith("*")
            word = parse(word)

            if word in split_name:
                return True

            elif any_start and any_end:
                if contains(name, word[1:-1], parse=False):
                    return True

            elif any_start:
                for subword in split_name:
                    if subword.endswith(word[1:]):
                        return True

            elif any_end:
                for subword in split_name:
                    if subword.startswith(word[:-1]):
                        return True

        return False
