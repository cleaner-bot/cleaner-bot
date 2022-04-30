import asyncio
from datetime import datetime
import logging
import typing

import hikari
import msgpack  # type: ignore

from cleaner_i18n.translate import Message
from cleaner_conf.guild import GuildConfig, GuildEntitlements

from ..bot import TheCleaner
from ..shared.event import ILog
from ..shared.protect import protect, protected_call
from ..shared.sub import listen as pubsub_listen, Message as PubMessage
from ..shared.dangerous import DANGEROUS_PERMISSIONS

logger = logging.getLogger(__name__)


class VerificationExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    kicks: dict[int, dict[int, float]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.MemberCreateEvent, self.on_member_create),
            (hikari.MemberDeleteEvent, self.on_member_delete),
        ]
        self.task = None

    def on_load(self):
        self.task = asyncio.create_task(protect(self.verifyd))

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def on_member_create(self, event: hikari.MemberCreateEvent):
        await self.bot.database.set(
            f"guild:{event.guild_id}:user:{event.user_id}:verification", "1", ex=600
        )

    async def on_member_delete(self, event: hikari.MemberDeleteEvent):
        await self.bot.database.delete(
            f"guild:{event.guild_id}:user:{event.user_id}:verification"
        )

    @staticmethod
    def check_guild(guild: hikari.Guild) -> bool:
        me = guild.get_my_member()
        if me is None:
            return False
        for role in me.get_roles():
            if role.permissions & (
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.KICK_MEMBERS
            ):
                return True
        return False

    async def verifyd(self):
        pubsub = self.bot.database.pubsub()
        await pubsub.subscribe("pubsub:verification-verify")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, PubMessage):
                continue

            data = msgpack.unpackb(event.data)
            asyncio.create_task(
                protected_call(self.verify_user(data["guild"], data["user"]))
            )

    async def verify_user(self, guild_id: int, user_id: int):
        guild = self.bot.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(f"uncached guild: {int(guild_id)}")
            return
        config = self.get_config(guild.id)

        if config is None:
            logger.warning(f"uncached guild settings: {guild.id}")
            return

        if not config.verification_enabled:
            return
        elif not await self.bot.database.exists(
            (f"guild:{guild_id}:user:{user_id}:verification",)
        ):
            return

        await self.bot.database.delete(
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

        await self.bot.bot.rest.add_role_to_member(guild.id, user_id, role.id)

        if config.logging_enabled and config.logging_option_verify:
            log = ILog(
                guild.id,
                Message("components_log_verify_verification", {"user": user_id}),
                datetime.utcnow(),
            )
            http = self.bot.extensions.get("clend.http", None)
            if http is None:
                logger.warning("tried to log http extension is not loaded")
            else:
                http.queue.sync_q.put(log)

    def get_config(self, guild_id: int) -> GuildConfig | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_config(guild_id)

    def get_entitlements(self, guild_id: int) -> GuildEntitlements | None:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None

        return conf.get_entitlements(guild_id)
