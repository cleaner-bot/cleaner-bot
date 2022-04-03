import asyncio
import logging
import time
import typing

import hikari
import msgpack  # type: ignore

from cleaner_conf.guild import GuildConfig, GuildEntitlements
from cleaner_i18n.translate import Message as TLMessage

from ..bot import TheCleaner
from ..shared.protect import protect, protected_call
from ..shared.sub import listen as pubsub_listen, Message
from ..shared.custom_events import TimerEvent
from ..shared.event import IActionChallenge
from ..shared.dangerous import DANGEROUS_PERMISSIONS

logger = logging.getLogger(__name__)


class VerificationExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]
    kicks: dict[int, dict[int, float]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.MemberCreateEvent, self.on_member_create),
            (TimerEvent, self.on_timer),
        ]
        self.task = None
        self.kicks = {}

    def on_load(self):
        self.task = asyncio.create_task(protect(self.verifyd))

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def on_member_create(self, event: hikari.MemberCreateEvent):
        await self.bot.database.set(
            f"guild:{event.guild_id}:user:{event.user_id}:verification", "1", ex=600
        )
        if event.guild_id not in self.kicks:
            self.kicks[event.guild_id] = {}
        self.kicks[event.guild_id][event.user_id] = time.monotonic()

    async def on_member_delete(self, event: hikari.MemberDeleteEvent):
        await self.bot.database.delete(
            f"guild:{event.guild_id}:user:{event.user_id}:verification"
        )
        if event.guild_id not in self.kicks:
            return
        kicks = self.kicks[event.guild_id]
        if event.user_id not in kicks:
            return
        del kicks[event.user_id]

    async def on_timer(self, event: TimerEvent):
        now = time.monotonic()
        actions = []

        info = {"name": "verification", "action": "kick"}
        for guild_id, guild_users in tuple(self.kicks.items()):
            guild = self.bot.bot.cache.get_guild(guild_id)
            if guild is None or not self.check_guild(guild):
                del self.kicks[guild_id]
                continue
            config = self.get_config(guild_id)
            if config is None or not config.verification_enabled:
                continue

            for user_id, expire in tuple(guild_users.items()):
                if now < expire + 8 * 60:
                    continue
                del guild_users[user_id]
                member = guild.get_member(user_id)
                # > 1 because everyone role
                if member is None or len(member.role_ids) > 1:
                    continue

                message = TLMessage("verification_kick_reason", {"user": user_id})
                action = IActionChallenge(
                    guild_id,
                    user_id,
                    False,  # block
                    False,  # can_ban
                    True,  # can_kick
                    False,  # can_timeout
                    False,  # can_role
                    False,  # take_role
                    0,  # role_id
                    message,
                    info,
                )
                actions.append(action)

        if not actions:
            return

        http = self.bot.extensions.get("clend.http", None)
        if http is None:
            logger.warning("action required but http extension is not loaded")
        else:
            for item in actions:
                await http.queue.async_q.put(item)

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
            if not isinstance(event, Message):
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
        if guild_id in self.kicks:  # bot might've restarted
            kicks = self.kicks[guild_id]
            if user_id in kicks:
                del kicks[user_id]

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
