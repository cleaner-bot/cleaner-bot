import string

import hikari
from hikari.internal.time import utc_datetime

from ._types import ConfigType, DehoistTriggeredEvent, KernelType
from .helpers.localization import Message
from .helpers.task import complain_if_none, safe_background_call

DEHOIST_CHARS = string.whitespace + string.punctuation


class DehoistService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["dehoist:create"] = self.dehoist
        self.kernel.bindings["dehoist:update"] = self.member_update

    async def member_update(
        self, event: hikari.MemberUpdateEvent, config: ConfigType
    ) -> bool:
        if (
            event.old_member is None
            or event.old_member.display_name == event.member.display_name
        ) and (utc_datetime() - event.member.joined_at).total_seconds() < 5:
            return False
        return await self.dehoist(event.member, config)

    async def dehoist(self, member: hikari.Member, config: ConfigType) -> bool:
        if set(config["name_roles"]) & set(map(str, member.role_ids)):
            return False

        new_nickname = self.nickname(member)
        if new_nickname is hikari.UNDEFINED:
            return False

        if nickname := complain_if_none(
            self.kernel.bindings.get("http:nickname"), "http:nickname"
        ):
            if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
                info: DehoistTriggeredEvent = {
                    "name": "dehoist",
                    "guild_id": member.guild_id,
                }
                safe_background_call(track(info))

            reason = Message("log_dehoist")
            safe_background_call(nickname(member, new_nickname, reason))

        return True

    def nickname(self, member: hikari.Member) -> hikari.UndefinedNoneOr[str]:
        nickname = member.display_name.lstrip(DEHOIST_CHARS)

        # empty display_name, contains only dehoistable
        if not nickname and member.global_name:
            if not member.global_name.startswith(DEHOIST_CHARS):
                # global name is ok, so reset nickname
                return None
            nickname = member.global_name.lstrip(DEHOIST_CHARS)

        # empty nickname and global name
        if not nickname:
            nickname = member.username.lstrip(DEHOIST_CHARS)

        # empty user_name, contains only dehoistable, so change to "dehoisted"
        if not nickname or nickname == member.username:
            nickname = "dehoisted"

        # setting the nickname to the username will reset the nickname and
        # show the global name instead, which would bypass our filters
        if nickname == member.username:
            nickname += "_"

        # return UNDEFINED if no changes are made
        return hikari.UNDEFINED if nickname == member.display_name else nickname
