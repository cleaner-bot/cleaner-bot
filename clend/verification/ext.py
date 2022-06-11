import asyncio
import logging
import typing
from datetime import datetime

import hikari
import msgpack  # type: ignore
from cleaner_i18n import Message

from ..app import TheCleanerApp
from ..shared.dangerous import DANGEROUS_PERMISSIONS
from ..shared.event import ILog
from ..shared.protect import protect, protected_call
from ..shared.sub import Message as PubMessage
from ..shared.sub import listen as pubsub_listen

logger = logging.getLogger(__name__)


class VerificationExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]
    kicks: dict[int, dict[int, float]]
    task: asyncio.Task[None] | None = None

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = [
            (hikari.MemberCreateEvent, self.on_member_create),
            (hikari.MemberDeleteEvent, self.on_member_delete),
        ]

    def on_load(self) -> None:
        self.task = asyncio.create_task(protect(self.verifyd))

    def on_unload(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def on_member_create(self, event: hikari.MemberCreateEvent) -> None:
        await self.app.database.set(
            f"guild:{event.guild_id}:user:{event.user_id}:verification", "1", ex=600
        )

    async def on_member_delete(self, event: hikari.MemberDeleteEvent) -> None:
        await self.app.database.delete(
            (f"guild:{event.guild_id}:user:{event.user_id}:verification",)
        )

    async def verifyd(self) -> None:
        pubsub = self.app.database.pubsub()
        await pubsub.subscribe("pubsub:verification-verify")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, PubMessage):
                continue

            data = msgpack.unpackb(event.data)
            asyncio.create_task(
                protected_call(self.verify_user(data["guild"], data["user"]))
            )

    async def verify_user(self, guild_id: int, user_id: int) -> None:
        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(f"uncached guild: {int(guild_id)}")
            return
        data = self.app.store.get_data(guild.id)

        if data is None:
            logger.warning(f"uncached guild settings: {guild.id}")
            return

        config = data.config

        if not config.verification_enabled:
            return
        elif not await self.app.database.exists(
            (f"guild:{guild_id}:user:{user_id}:verification",)
        ):
            return

        await self.app.database.delete(
            (f"guild:{guild_id}:user:{user_id}:verification",)
        )

        role = guild.get_role(int(config.verification_role))
        if (
            role is None
            or role.is_managed
            or role.position == 0
            or role.permissions & DANGEROUS_PERMISSIONS
        ):
            return

        me = guild.get_my_member()
        if me is None:
            return

        top_role = me.get_top_role()
        if top_role is not None and role.position >= top_role.position:
            return

        for my_role in me.get_roles():
            if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            return

        await self.app.bot.rest.add_role_to_member(guild.id, user_id, role.id)

        if config.logging_enabled and config.logging_option_verify:
            user = self.app.bot.cache.get_user(user_id)
            if user is None:
                user = await self.app.bot.rest.fetch_user(user_id)

            log = ILog(
                guild.id,
                Message(
                    "components_log_verify_verification",
                    {"user": user_id, "name": str(user)},
                ),
                datetime.utcnow(),
            )
            self.app.store.put_http(log)
