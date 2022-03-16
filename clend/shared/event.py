import typing

import hikari


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

    user_id: int
    reason: str


class IActionChallenge(typing.NamedTuple):
    guild_id: int
    user_id: int
    block: bool
    can_ban: bool
    can_kick: bool
    can_timeout: bool
    can_role: bool
    take_role: bool
    role_id: int
    reason: str


class IActionDelete(typing.NamedTuple):
    guild_id: int
    user_id: int
    channel_id: int
    message_id: int
    can_delete: bool
    reason: str
    message: typing.Optional[hikari.Message]


class IActionNickname(typing.NamedTuple):
    guild_id: int
    user_id: int
    can_reset: bool
    reason: str


class IActionAnnouncement(typing.NamedTuple):
    guild_id: int
    channel_id: int
    can_send: bool
    announcement: str
    delete_after: float


class IActionChannelRatelimit(typing.NamedTuple):
    guild_id: int
    channel_id: int
    ratelimit: int
    can_modify: bool


class ILog(typing.NamedTuple):
    guild_id: int
    message: str
    referenced_message: typing.Optional[hikari.Message]
