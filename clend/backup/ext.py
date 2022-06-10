import asyncio
import logging
import typing
from datetime import datetime

import hikari
import msgpack  # type: ignore

from ..app import TheCleanerApp
from ..shared.protect import protect, protected_call
from ..shared.sub import Message, listen
from .types import Snapshot, SnapshotChannel, SnapshotChannelKeys, SnapshotRole

logger = logging.getLogger(__name__)


def name_diff(snapshot: dict[int, str], after: dict[int, str]) -> dict[int, int]:
    result = {k: k for k in snapshot.keys() if k in after}
    deleted_channels = set(snapshot.keys()) - set(after.keys())
    name_map = {after[k]: k for k in after if k not in result}
    for k in deleted_channels:
        name = snapshot[k]
        if name in name_map:
            result[k] = name_map[name]
            del name_map[name]
        else:
            result[k] = 0

    return result


def calc_channel_diff(
    channel: hikari.GuildChannel, snapshot: SnapshotChannel
) -> dict[str, typing.Any]:
    new_snapshot = make_channel_snapshot(channel)
    # mypy does not like dynamic keys into a TypedDict
    return {
        k: v
        for k, v in snapshot.items()
        if new_snapshot[typing.cast(SnapshotChannelKeys, k)] != v
    }


def make_channel_snapshot(channel: hikari.GuildChannel) -> SnapshotChannel:
    assert channel.name is not None, "impossible for a GuildChannel"
    return {
        "id": channel.id,
        "type": channel.type,
        "position": channel.position,
        "permissions_overwrites": [
            {
                "id": overwrite.id,
                "type": overwrite.type,
                "allow": overwrite.allow,
                "deny": overwrite.deny,
            }
            for overwrite in channel.permission_overwrites.values()
        ],
        "is_nsfw": channel.is_nsfw,
        "parent_id": channel.parent_id,
        "name": channel.name,
        "topic": getattr(channel, "topic", None),
        "rate_limit_per_user": (
            int(channel.rate_limit_per_user.total_seconds())
            if isinstance(channel, hikari.GuildTextChannel)
            else None
        ),
        "bitrate": getattr(channel, "bitrate", None),
        "region": getattr(channel, "region", None),
        "user_limit": getattr(channel, "user_limit", None),
        "video_quality_mode": getattr(channel, "video_quality_mode", None),
    }


def make_role_snapshot(role: hikari.Role) -> SnapshotRole:
    return {
        "id": role.id,
        "name": role.name,
        "color": role.color,
        "is_hoisted": role.is_hoisted,
        "is_managed": role.is_managed,
        "is_mentionable": role.is_mentionable,
        "permissions": role.permissions,
    }


class BackupExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]
    task: asyncio.Task[None] | None = None

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = []

    def on_load(self) -> None:
        self.task = asyncio.ensure_future(protect(self.backup_task))

    def on_unload(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def backup_task(self) -> None:
        pubsub = self.app.database.pubsub()
        await pubsub.subscribe("pubsub:backup:snapshot")
        await pubsub.subscribe("pubsub:backup:apply-snapshot")
        async for event in listen(pubsub):
            if not isinstance(event, Message):
                continue

            guild_id, snapshot_id = event.data.decode().split(":")
            coro = (
                self.apply_snapshot
                if event.channel.endswith(b"apply-snapshot")
                else self.create_snapshot
            )
            asyncio.create_task(protected_call(coro(guild_id, snapshot_id)))

    async def apply_snapshot(self, guild_id: str, snapshot_id: str) -> None:
        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(
                f"tried to apply snapshot {snapshot_id} for {guild_id} but "
                "the guild wasnt in cache"
            )
            return

        snapshot_raw = await self.app.database.hget(
            f"guild:{guild_id}:backup:snapshots", snapshot_id
        )
        if snapshot_raw is None:
            logger.warning(
                f"tried to apply snapshot {snapshot_id} for {guild_id} but "
                "the snapshot is not in the db"
            )
            return

        snapshot: Snapshot = msgpack.unpackb(snapshot_raw)
        snapshot_channels = {x["id"]: x for x in snapshot["channels"]}
        # snapshot_roles = {x["id"]: x for x in snapshot["roles"]}

        logger.info(f"applying snapshot {snapshot_id} in {guild_id}")

        channel_diff = name_diff(
            {channel["id"]: channel["name"] for channel in snapshot["channels"]},
            {
                channel.id: channel.name
                for channel in guild.get_channels().values()
                if channel.name is not None
            },
        )
        for before, after in channel_diff.items():
            if after == 0:
                logger.debug(f"create channel: {before}")
            elif before != after:
                logger.debug(f"new channel id: {before} -> {after}")

        unexpected_channels = set(guild.get_channels().keys()) - set(
            channel_diff.values()  # type: ignore
        )
        for to_delete in unexpected_channels:
            logger.debug(f"delete channel: {to_delete}")

        for before, after in channel_diff.items():
            channel = guild.get_channel(after)
            if channel is None:  # TODO: replace with assert
                continue
            diff = calc_channel_diff(channel, snapshot_channels[before])
            if diff:
                logger.debug(f"channel diff for {before} -> {after}: {diff}")

        role_diff = name_diff(
            {role["id"]: role["name"] for role in snapshot["roles"]},
            {role.id: role.name for role in guild.get_roles().values()},
        )
        for before, after in role_diff.items():
            if after == 0:
                logger.debug(f"create role: {before}")
            elif before != after:
                logger.debug(f"new role id: {before} -> {after}")

        unexpected_roles = set(guild.get_roles().keys()) - set(
            role_diff.values()  # type: ignore
        )
        for to_delete in unexpected_roles:
            logger.debug(f"delete role: {to_delete}")

    async def create_snapshot(self, guild_id: str, snapshot_id: str) -> None:
        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(
                f"tried to create snapshot {snapshot_id} for {guild_id} but "
                "the guild wasnt in cache"
            )
            return

        data: Snapshot = {
            "guild": {
                "name": guild.name,
                "afk_channel_id": guild.afk_channel_id,
                "afk_timeout": int(guild.afk_timeout.total_seconds()),
                "system_channel_id": guild.system_channel_id,
                "system_channel_flags": guild.system_channel_flags,
                "public_updates_channel_id": guild.public_updates_channel_id,
                "rules_channel_id": guild.rules_channel_id,
                "widget_channel_id": guild.widget_channel_id,
                "verification_level": guild.verification_level,
                "explicit_content_filter": guild.explicit_content_filter,
            },
            "channels": [
                make_channel_snapshot(channel)
                for channel in guild.get_channels().values()
            ],
            "roles": [make_role_snapshot(role) for role in guild.get_roles().values()],
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.app.database.hset(
            f"guild:{guild_id}:backup:snapshots", {snapshot_id: msgpack.packb(data)}
        )
        await self.app.database.publish(f"pubsub:backup:snapshot:{snapshot_id}", "1")
        logger.info(f"created snapshot {snapshot_id} for {guild_id}")
