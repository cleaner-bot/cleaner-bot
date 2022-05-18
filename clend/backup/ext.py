import asyncio
import logging
import typing
from datetime import datetime

import hikari
import msgpack  # type: ignore

from ..app import TheCleanerApp
from ..shared.sub import Message, listen

logger = logging.getLogger(__name__)


class BackupExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    task: asyncio.Task | None = None

    def __init__(self, app: TheCleanerApp):
        self.app = app
        self.listeners = []

    def on_load(self):
        self.task = asyncio.ensure_future(self.backup_task())

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def backup_task(self):
        pubsub = self.app.database.pubsub()
        await pubsub.subscribe("pubsub:backup:snapshot")
        await pubsub.subscribe("pubsub:backup:apply-snapshot")
        async for event in listen(pubsub):
            if not isinstance(event, Message):
                continue

            guild_id, snapshot_id = event.data.decode().split(":")
            if event.channel.endswith("apply-snapshot"):
                asyncio.create_task(self.apply_snapshot(guild_id, snapshot_id))
            else:
                asyncio.create_task(self.create_snapshot(guild_id, snapshot_id))

    async def apply_snapshot(self, guild_id: str, snapshot_id: str):
        pass

    async def create_snapshot(self, guild_id: str, snapshot_id: str):
        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(
                f"tried to create snapshot {snapshot_id} for {guild_id} but "
                "the guild wasnt in cache"
            )
            return

        data = {
            "guild": {
                "name": guild.name,
                "afk_channel_id": guild.afk_channel_id,
                "afk_timeout": guild.afk_timeout.total_seconds(),
                "system_channel_id": guild.system_channel_id,
                "system_channel_flags": guild.system_channel_flags,
                "public_updates_channel_id": guild.public_updates_channel_id,
                "rules_channel_id": guild.rules_channel_id,
                "widget_channel_id": guild.widget_channel_id,
                "verification_level": guild.verification_level,
                "explicit_content_filter": guild.explicit_content_filter,
            },
            "channels": [
                {
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
                    "rate_limit_per_user": getattr(
                        channel, "rate_limit_per_user", None
                    ),
                    "bitrate": getattr(channel, "bitrate", None),
                    "region": getattr(channel, "region", None),
                    "user_limit": getattr(channel, "user_limit", None),
                    "video_quality_mode": getattr(channel, "video_quality_mode", None),
                }
                for channel in guild.get_channels().values()
            ],
            "roles": [
                {
                    "id": role.id,
                    "name": role.name,
                    "color": role.color,
                    "is_hoisted": role.is_hoisted,
                    "is_managed": role.is_managed,
                    "is_mentionable": role.is_mentionable,
                    "permissions": role.permissions,
                }
                for role in guild.get_roles().values()
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.app.database.hset(
            f"guild:{guild_id}:backup:snapshots", {snapshot_id: msgpack.packb(data)}
        )
        await self.app.database.publish(f"pubsub:backup:snapshot:{snapshot_id}", "")
        logger.info(f"created snapshot {snapshot_id} for {guild_id}")
