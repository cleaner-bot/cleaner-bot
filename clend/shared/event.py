import typing

import hikari

from cleaner_i18n.translate import translate


class Translateable(typing.NamedTuple):
    translate_key: str
    variables: dict[str, typing.Any]

    def translate(self, locale: str) -> str:
        return translate(locale, self.translate_key, **self.variables)


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
    reason: Translateable
    info: typing.Any


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
    reason: Translateable
    info: typing.Any


class IActionDelete(typing.NamedTuple):
    guild_id: int
    user_id: int
    channel_id: int
    message_id: int
    can_delete: bool
    message: typing.Optional[hikari.Message]
    reason: Translateable
    info: typing.Any


class IActionNickname(typing.NamedTuple):
    guild_id: int
    user_id: int
    can_reset: bool
    reason: Translateable
    info: typing.Any


class IActionAnnouncement(typing.NamedTuple):
    guild_id: int
    channel_id: int
    can_send: bool
    announcement: Translateable
    delete_after: float


class IActionChannelRatelimit(typing.NamedTuple):
    guild_id: int
    channel_id: int
    ratelimit: int
    can_modify: bool


class ILog(typing.NamedTuple):
    guild_id: int
    message: Translateable
    reason: typing.Optional[Translateable] = None
    referenced_message: typing.Optional[hikari.Message] = None
