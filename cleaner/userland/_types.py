from __future__ import annotations

import typing
from datetime import datetime

import hikari
from coredis import Redis

from .helpers.localization import Message


class KernelType(typing.Protocol):
    bot: hikari.GatewayBot
    database: Redis[bytes]
    extensions: dict[str, typing.Any]

    bindings: Bindings  # ipc
    rpc: RPC
    longterm: LongTerm  # longterm storage for keeping track of stuff between reloads
    interactions: Interactions
    data: Data  # really longterm

    def load_extension(self, module: str) -> None:
        ...

    def unload_extension(self, module: str) -> None:
        ...

    @staticmethod
    def is_developer(user_id: int) -> bool:
        ...

    def translate(self, language: str, key: str, /, **kwargs: str) -> str:
        ...


class ConfigType(typing.TypedDict):
    rules_phishing_content: int
    rules_phishing_content_channels: list[str]
    rules_phishing_domain_blacklisted: int
    rules_phishing_domain_blacklisted_channels: list[str]
    rules_phishing_domain_heuristic: int
    rules_phishing_domain_heuristic_channels: list[str]
    rules_phishing_embed: int
    rules_phishing_embed_channels: list[str]
    rules_selfbot_embed: int
    rules_selfbot_embed_channels: list[str]
    rules_ping_hidden: int
    rules_ping_hidden_channels: list[str]
    rules_ping_roles: int
    rules_ping_roles_channels: list[str]
    rules_ping_users_many: int
    rules_ping_users_many_channels: list[str]
    rules_ping_users_few: int
    rules_ping_users_few_channels: list[str]
    rules_ping_broad: int
    rules_ping_broad_channels: list[str]
    rules_advertisement_discord_invite: int
    rules_advertisement_discord_invite_channels: list[str]
    rules_advertisement_discord_unsafeinvite: int
    rules_advertisement_discord_unsafeinvite_channels: list[str]
    rules_emoji_mass: int
    rules_emoji_mass_channels: list[str]
    antispam_similar: bool
    antispam_similar_channels: list[str]
    antispam_exact: bool
    antispam_exact_channels: list[str]
    antispam_token: bool
    antispam_token_channels: list[str]
    antispam_sticker: bool
    antispam_sticker_channels: list[str]
    antispam_attachment: bool
    antispam_attachment_channels: list[str]
    antispam_anomaly: bool
    antispam_anomaly_channels: list[str]
    antispam_anomaly_score: int
    antiraid_enabled: bool
    antiraid_limit: str
    antiraid_mode: int
    general_modroles: list[str]
    slowmode_enabled: bool
    slowmode_exceptions: list[str]
    punishments_timeout_enabled: bool
    punishments_verification_enabled: bool
    verification_enabled: bool
    verification_role: str
    verification_take_role: bool
    verification_age: int
    super_verification_enabled: bool
    super_verification_captcha: bool
    super_verification_role: str
    verification_timelimit_enabled: bool
    verification_timelimit: int
    logging_enabled: bool
    logging_channel: str
    logging_option_join: bool
    logging_option_join_risky: bool
    logging_option_leave: bool
    name_dehoisting_enabled: bool
    name_discord_enabled: bool
    name_advanced_enabled: bool
    name_advanced_words: list[str]
    joinguard_enabled: bool
    joinguard_captcha: bool
    report_enabled: bool
    report_channel: str
    branding_splash_enabled: bool
    branding_embed_enabled: bool
    branding_embed_title: str
    branding_embed_description: str
    access_permissions: int
    access_members: list[str]
    access_mfa: bool
    antinuke_bots: int
    antinuke_webhooks: bool
    auth_enabled: bool
    auth_roles: dict[str, list[str]]
    bansync_subscribed: list[str]
    linkfilter_enabled: bool
    linkfilter_channel: str
    linkfilter_blockunknown: bool


class EntitlementsType(typing.TypedDict):
    plan: int
    suspended: str
    partnered: bool
    access: int
    antiraid: int
    antispam: int
    branding_splash: int
    branding_embed: int
    branding_vanity: int
    branding_vanity_url: str
    contact_standard: int
    contact_email: int
    automod: int
    name_advanced: int
    joinguard: int
    logging: int
    logging_downloads: int
    logging_retention: int
    slowmode: int
    statistics: int
    report: int
    verification: int
    super_verification: int
    verification_timelimit: int
    bansync_subscription_limit: int
    auth: int
    linkfilter: int


class AntiSpamTriggeredEvent(typing.TypedDict):
    name: typing.Literal["antispam"]
    guild_id: int
    initial: bool
    rule: str
    id: str  # internal id of the antispam rule


class AutoModTriggeredEvent(typing.TypedDict):
    name: typing.Literal["automod"]
    guild_id: int
    rule: str


class SlowmodeTriggeredEvent(typing.TypedDict):
    name: typing.Literal["slowmode"]
    guild_id: int
    emergency: bool
    rate_limit_per_user: int


class SuspendedActionEvent(typing.TypedDict):
    name: typing.Literal["suspended"]
    guild_id: int
    type: typing.Literal["user", "guild"]
    reason: str


class JoinGuardTriggeredEvent(typing.TypedDict):
    name: typing.Literal["joinguard"]
    guild_id: int


class AntiRaidTriggeredEvent(typing.TypedDict):
    name: typing.Literal["antiraid"]
    guild_id: int
    limit: str
    id: int


class NameTriggeredEvent(typing.TypedDict):
    name: typing.Literal["name"]
    guild_id: int
    detection: typing.Literal["discord", "custom"]
    id: int


class TimeLimitTriggeredEvent(typing.TypedDict):
    name: typing.Literal["timelimit"]
    guild_id: int


class DehoistTriggeredEvent(typing.TypedDict):
    name: typing.Literal["dehoist"]
    guild_id: int


class BanSyncTriggeredEvent(typing.TypedDict):
    name: typing.Literal["bansync"]
    guild_id: int
    list_id: int


class RaidDetectedEvent(typing.TypedDict):
    name: typing.Literal["raid"]
    guild_id: int
    start: int
    end: int
    kicks: int
    bans: int


class PunishmentEvent(typing.TypedDict):
    name: typing.Literal["punishment"]
    guild_id: int
    action: str


class LinkFilteredEvent(typing.TypedDict):
    name: typing.Literal["linkfilter"]
    guild_id: int
    url: str


EventType = (
    AntiSpamTriggeredEvent
    | AutoModTriggeredEvent
    | SlowmodeTriggeredEvent
    | SuspendedActionEvent
    | JoinGuardTriggeredEvent
    | AntiRaidTriggeredEvent
    | NameTriggeredEvent
    | TimeLimitTriggeredEvent
    | DehoistTriggeredEvent
    | BanSyncTriggeredEvent
    | RaidDetectedEvent
    | PunishmentEvent
    | LinkFilteredEvent
)


class InteractionResponse(typing.TypedDict, total=False):
    content: str
    flags: typing.Union[int, hikari.MessageFlag, hikari.UndefinedType]
    attachment: hikari.Resourceish
    attachments: typing.Sequence[hikari.Resourceish] | None
    component: hikari.api.ComponentBuilder
    components: typing.Sequence[hikari.api.ComponentBuilder]
    embed: hikari.Embed
    embeds: typing.Sequence[hikari.Embed]
    mentions_everyone: bool
    user_mentions: bool | hikari.SnowflakeishSequence[hikari.PartialUser]
    role_mentions: bool | hikari.SnowflakeishSequence[hikari.PartialRole]


class Interactions(typing.TypedDict):
    commands: dict[
        str,
        typing.Callable[
            [hikari.CommandInteraction], typing.Awaitable[InteractionResponse | None]
        ],
    ]
    components: dict[
        str,
        typing.Callable[..., typing.Awaitable[InteractionResponse | None]],
    ]
    modals: dict[
        str,
        typing.Callable[..., typing.Awaitable[InteractionResponse | None]],
    ]


ReturnType = typing.TypeVar("ReturnType")
MessageCoroutine = typing.Callable[
    [hikari.Message, ConfigType, EntitlementsType], typing.Awaitable[ReturnType]
]
MemberCoroutine = typing.Callable[
    [hikari.Member, ConfigType, EntitlementsType], typing.Awaitable[ReturnType]
]
PartialMessageCoroutine = typing.Callable[
    [hikari.PartialMessage, ConfigType, EntitlementsType], typing.Awaitable[ReturnType]
]
Bindings = typing.TypedDict(
    "Bindings",
    {
        "traffic": MessageCoroutine[None],
        "slowmode": MessageCoroutine[None],
        "slowmode:timer": typing.Callable[[], typing.Awaitable[None]],
        "antispam": MessageCoroutine[bool],
        "automod": PartialMessageCoroutine[bool],
        "linkfilter": PartialMessageCoroutine[bool],
        "dev": MessageCoroutine[None],
        "suspension:user": MemberCoroutine[bool],
        "suspension:guild": typing.Callable[
            [hikari.GatewayGuild, EntitlementsType], typing.Awaitable[bool]
        ],
        "joinguard": MemberCoroutine[bool],
        "antiraid": MemberCoroutine[bool],
        "name:create": MemberCoroutine[bool],
        "name:update": typing.Callable[
            [hikari.MemberUpdateEvent, ConfigType, EntitlementsType],
            typing.Awaitable[bool],
        ],
        "timelimit:create": typing.Callable[[hikari.Member], typing.Awaitable[None]],
        "timelimit:delete": typing.Callable[
            [hikari.Snowflake, hikari.Snowflake], typing.Awaitable[None]
        ],
        "timelimit:timer": typing.Callable[[], typing.Awaitable[None]],
        "log": typing.Callable[
            [
                hikari.SnowflakeishOr[hikari.Guild],
                Message,
                Message | None,
                hikari.PartialMessage | None,
            ],
            typing.Awaitable[None],
        ],
        "log:member:create": typing.Callable[[hikari.Member], typing.Awaitable[None]],
        "log:member:delete": typing.Callable[
            [hikari.Snowflake, hikari.Snowflake], typing.Awaitable[None]
        ],
        "log:guild:join": typing.Callable[
            [hikari.GatewayGuild, EntitlementsType], typing.Awaitable[None]
        ],
        "log:guild:leave": typing.Callable[
            [int, hikari.GatewayGuild | None, EntitlementsType], typing.Awaitable[None]
        ],
        "log:raid:complete": typing.Callable[
            [int, datetime, datetime, int, int], typing.Awaitable[None]
        ],
        "log:raid:ongoing": typing.Callable[
            [int, datetime, int, int], typing.Awaitable[None]
        ],
        "dehoist:create": typing.Callable[[hikari.Member], typing.Awaitable[bool]],
        "dehoist:update": typing.Callable[
            [hikari.MemberUpdateEvent], typing.Awaitable[bool]
        ],
        "bansync:ban": typing.Callable[
            [hikari.Member, ConfigType, str], typing.Awaitable[None]
        ],
        "bansync:ban:create": typing.Callable[
            [hikari.BanCreateEvent], typing.Awaitable[None]
        ],
        "bansync:ban:delete": typing.Callable[
            [hikari.BanDeleteEvent], typing.Awaitable[None]
        ],
        "bansync:member:create": typing.Callable[
            [hikari.Member, ConfigType, EntitlementsType], typing.Awaitable[bool]
        ],
        "radar:message": MessageCoroutine[None],
        "radar:timer": typing.Callable[[], typing.Awaitable[None]],
        "radar:raid:submit": typing.Callable[
            [hikari.Member, typing.Literal["kick", "ban"]], typing.Awaitable[None]
        ],
        "radar:phishing:submit": typing.Callable[
            [hikari.Message, str], typing.Awaitable[None]
        ],
        "radar:unsafeinvite:submit": typing.Callable[
            [hikari.Message], typing.Awaitable[None]
        ],
        "integration:timer": typing.Callable[[], typing.Awaitable[None]],
        "members:timer": typing.Callable[[], typing.Awaitable[None]],
        "members:guild:available": typing.Callable[
            [hikari.GatewayGuild], typing.Awaitable[None]
        ],
        "members:guild:delete": typing.Callable[[int], typing.Awaitable[None]],
        "members:member:create": typing.Callable[[int], typing.Awaitable[None]],
        "members:member:delete": typing.Callable[[int], typing.Awaitable[None]],
        "data:load": typing.Callable[[str | None], bool | None],
        "data:save": typing.Callable[[str | None], bool | None],
        "data:changed": typing.Callable[[str], None],
        "http:challenge": typing.Callable[
            [hikari.Member, ConfigType, bool, Message, int],
            typing.Awaitable[None],
        ],
        "http:delete": typing.Callable[
            [
                int,
                int,
                hikari.SnowflakeishOr[hikari.User],
                bool,
                Message | None,
                hikari.PartialMessage | None,
            ],
            typing.Awaitable[None],
        ],
        "http:nickname": typing.Callable[
            [hikari.Member, str | None, Message],
            typing.Awaitable[None],
        ],
        "http:announcement": typing.Callable[
            [int, int, Message, float],
            typing.Awaitable[None],
        ],
        "http:channel_ratelimit": typing.Callable[
            [hikari.GuildTextChannel, int], typing.Awaitable[None]
        ],
        "http:danger_level": typing.Callable[[int], int],
        "http:member:create": typing.Callable[[hikari.Member], typing.Awaitable[None]],
        "verification:issue": typing.Callable[
            [
                hikari.ComponentInteraction,
                hikari.Guild,
                int,
                bool,
            ],
            typing.Awaitable[InteractionResponse | None],
        ],
        "verification:check": typing.Callable[
            [hikari.Guild, hikari.Member, str, ConfigType],
            typing.Awaitable[InteractionResponse | None],
        ],
        "verification:solved": typing.Callable[
            [hikari.Member, ConfigType, str], typing.Awaitable[InteractionResponse]
        ],
        "verification:external:issue": typing.Callable[
            [hikari.ComponentInteraction], typing.Awaitable[InteractionResponse | None]
        ],
        "verification:discord:issue": typing.Callable[
            [hikari.Member, int, str], typing.Awaitable[InteractionResponse | None]
        ],
        "mfa:request": typing.Callable[
            [
                hikari.CommandInteraction
                | hikari.ComponentInteraction
                | hikari.ModalInteraction,
                str,
                str,
            ],
            typing.Awaitable[InteractionResponse],
        ],
        "track": typing.Callable[[EventType], typing.Awaitable[None]],
        "statistics:save": typing.Callable[[], typing.Awaitable[None]],
    },
)


class InteractionDatabaseType(typing.TypedDict):
    id: str
    application_id: str
    token: str
    message_id: str
    locale: str


class RPCResponse(typing.TypedDict):
    ok: bool
    message: str
    data: typing.Any | None


RPC = typing.TypedDict(
    "RPC",
    {
        "verification:post-message": typing.Callable[
            [int, int], typing.Awaitable[RPCResponse]
        ],
        "verification:external:verify": typing.Callable[
            [int, int, InteractionDatabaseType], typing.Awaitable[RPCResponse]
        ],
        "super-verification": typing.Callable[
            [int, int], typing.Awaitable[RPCResponse]
        ],
        "joinguard": typing.Callable[[int, int, str], typing.Awaitable[RPCResponse]],
        "dash:guild-check": typing.Callable[
            [tuple[int, ...]], typing.Awaitable[RPCResponse]
        ],
        "dash:guild-info": typing.Callable[[int], typing.Awaitable[RPCResponse]],
        "bansync:import": typing.Callable[[int, int], typing.Awaitable[RPCResponse]],
    },
)

LongTerm = typing.TypedDict(
    "LongTerm",
    {
        "member_counts": dict[int, int],
        "total_messages": int,
        "fetched_member_guilds": set[int],
    },
)


class Data(typing.TypedDict):
    localization: dict[str, dict[str, str]]
    discord_impersonation_avatars: list[str]
    discord_impersonation_names: list[str]
    phishing_domain_blacklist: list[str]
    phishing_domain_whitelist: list[str]
    phishing_embed_thumbnails: list[str]
    phishing_content: list[str]
    discord_invite_blacklist: list[str]
    config: ConfigType
    entitlements: EntitlementsType
