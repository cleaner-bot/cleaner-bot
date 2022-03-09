from dataclasses import dataclass
import typing

import hikari


class IGuildEvent(typing.Protocol):
    @property
    def guild_id(self) -> int: ...


class IGuildSettingsAvailable(typing.NamedTuple):
    guild_id: int


@dataclass
class IAction:
    guild_id: int
    user_id: int
    reason: str


@dataclass
class IActionChallenge(IAction):
    block: bool
    can_ban: bool
    can_kick: bool
    can_timeout: bool
    can_role: bool
    take_role: bool
    role_id: int = 0


@dataclass
class IDelete(IAction):
    channel_id: int
    message_id: int
    can_delete: bool


@dataclass
class IActionNickname(IAction):
    can_reset: bool


@dataclass
class IAnnouncement:
    guild_id: int
    channel_id: int
    can_send: bool
    announcement: str
    delete_after: float


@dataclass
class ILog:
    guild_id: int
    message: str
    referenced_message: typing.Optional[hikari.Message]
