import typing
from datetime import datetime

import hikari
from cleaner_i18n.translate import Message


class IGuildEvent(typing.Protocol):
    @property
    def guild_id(self) -> int:
        ...


class IGuildSettingsAvailable(typing.NamedTuple):
    guild_id: int


class IAction(typing.Protocol):
    @property
    def guild_id(self) -> int:
        ...

    user: hikari.User
    reason: Message
    info: typing.Any


class IActionChallenge(typing.NamedTuple):
    guild_id: int
    user: hikari.User
    block: bool
    can_ban: bool
    can_kick: bool
    can_timeout: bool
    can_role: bool
    take_role: bool
    role_id: int
    reason: Message
    info: typing.Any


class IActionDelete(typing.NamedTuple):
    guild_id: int
    user: hikari.User
    channel_id: int
    message_id: int
    can_delete: bool
    message: hikari.Message | None
    reason: Message
    info: typing.Any


class IActionNickname(typing.NamedTuple):
    guild_id: int
    user: hikari.User
    nickname: str | None
    can_change: bool
    can_kick: bool
    can_ban: bool
    reason: Message
    info: typing.Any


class IActionAnnouncement(typing.NamedTuple):
    guild_id: int
    channel_id: int
    can_send: bool
    announcement: Message
    delete_after: float


class IActionChannelRatelimit(typing.NamedTuple):
    guild_id: int
    channel_id: int
    ratelimit: int
    can_modify: bool


class ILog(typing.NamedTuple):
    guild_id: int
    message: Message
    created_at: datetime
    reason: Message | None = None
    referenced_message: hikari.Message | None = None
