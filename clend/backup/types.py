from __future__ import annotations

import typing


class Snapshot(typing.TypedDict):
    guild: SnapshotGuild
    channels: list[SnapshotChannel]
    roles: list[SnapshotRole]
    timestamp: str  # isoformat


class SnapshotGuild(typing.TypedDict):
    name: str
    afk_channel_id: int | None
    afk_timeout: int
    system_channel_id: int | None
    system_channel_flags: int
    public_updates_channel_id: int | None
    rules_channel_id: int | None
    widget_channel_id: int | None
    verification_level: int
    explicit_content_filter: int


SnapshotChannelKeys = typing.Literal[
    "id",
    "type",
    "position",
    "permissions_overwrites",
    "is_nsfw",
    "parent_id",
    "name",
    "topic",
    "rate_limit_per_user",
    "bitrate",
    "region",
    "user_limit",
    "video_quality_mode",
]


class SnapshotChannel(typing.TypedDict):
    id: int
    type: int
    position: int
    permissions_overwrites: list[SnapshotPermissionsOverwrite]
    is_nsfw: bool | None
    parent_id: int | None
    name: str
    topic: str | None
    rate_limit_per_user: int | None
    bitrate: int | None
    region: str | None
    user_limit: int | None
    video_quality_mode: int | None


class SnapshotPermissionsOverwrite(typing.TypedDict):
    id: int
    type: int
    allow: int
    deny: int


class SnapshotRole(typing.TypedDict):
    id: int
    name: str
    color: int
    is_hoisted: bool
    is_managed: bool
    is_mentionable: bool
    permissions: int
