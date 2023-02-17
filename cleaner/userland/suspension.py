import logging

import hikari

from ._types import ConfigType, EntitlementsType, KernelType, SuspendedActionEvent
from .helpers.localization import Message
from .helpers.task import complain_if_none, safe_background_call

logger = logging.getLogger(__name__)


class SuspensionService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["suspension:user"] = self.member_create
        self.kernel.bindings["suspension:guild"] = self.guild_create

    async def member_create(
        self, member: hikari.Member, config: ConfigType, entitlements: EntitlementsType
    ) -> bool:
        suspended = await self.kernel.database.hgetall(f"user:{member.id}:suspended")
        if not suspended:
            return False
        reason = suspended.get(b"reason", b"").decode()
        logger.debug(
            f"suspended user tried to join (user={member.id} guild={member.guild_id} "
            f"reason={reason!r})"
        )

        if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
            info: SuspendedActionEvent = {
                "name": "suspended",
                "guild_id": member.guild_id,
                "type": "user",
                "reason": reason,
            }
            safe_background_call(track(info))

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            log_reason = Message("log_suspension_user")
            safe_background_call(challenge(member, config, False, log_reason, 2))

        return True

    async def guild_create(
        self, guild: hikari.GatewayGuild, entitlements: EntitlementsType
    ) -> bool:
        if not entitlements["suspended"]:
            return False

        safe_background_call(self.kernel.bot.rest.leave_guild(guild))
        return True
