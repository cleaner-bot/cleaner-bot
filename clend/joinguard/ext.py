import asyncio
import logging
import typing

import hikari
import msgpack  # type: ignore
from cleaner_i18n import Message
from expirepy import ExpiringSet

from ..app import TheCleanerApp
from ..shared.event import IActionChallenge
from ..shared.protect import protect, protected_call
from ..shared.sub import Message as PubMessage
from ..shared.sub import listen as pubsub_listen

logger = logging.getLogger(__name__)


class JoinGuardExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Any]]
    whitelisted: ExpiringSet[int]
    task: asyncio.Task[None] | None = None

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.whitelisted = ExpiringSet(60)
        self.listeners = [
            (hikari.MemberCreateEvent, self.on_member_create),
        ]

    def on_load(self) -> None:
        self.task = asyncio.create_task(protect(self.verifyd))

    def on_unload(self) -> None:
        if self.task is not None:
            self.task.cancel()

    async def on_member_create(self, event: hikari.MemberCreateEvent) -> None:
        guild = event.get_guild()
        if event.member.id in self.whitelisted or guild is None:
            return
        data = self.app.store.get_data(event.guild_id)
        if data is None:
            logger.warning(f"uncached guild settings: {event.guild_id}")
            return

        if (
            not data.config.joinguard_enabled
            or data.entitlements.plan < data.entitlements.joinguard
        ):
            return

        can_kick = self.check_guild(guild)
        challenge = IActionChallenge(
            guild_id=event.guild_id,
            user=event.user,
            block=False,
            can_ban=False,
            can_kick=can_kick,
            can_timeout=False,
            can_role=False,
            take_role=False,
            role_id=0,
            reason=Message(
                "joinguard_reason_bypass",
                {"user": event.user_id, "name": str(event.user)},
            ),
            info={"name": "joinguard_bypass"},
        )
        self.app.store.put_http(challenge)

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

    async def verifyd(self) -> None:
        pubsub = self.app.database.pubsub()
        await pubsub.subscribe("pubsub:joinguard")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, PubMessage):
                continue

            data = msgpack.unpackb(event.data)
            asyncio.create_task(
                protected_call(
                    self.add_user(data["guild"], data["user"], data["token"])
                )
            )

    async def add_user(self, guild_id: int, user_id: int, token: str) -> None:
        guild = self.app.bot.cache.get_guild(int(guild_id))
        if guild is None:
            logger.warning(f"uncached guild: {int(guild_id)}")
            return
        data = self.app.store.get_data(guild.id)

        if data is None:
            logger.warning(f"uncached guild settings: {guild.id}")
            return

        if (
            not data.config.joinguard_enabled
            or data.entitlements.plan < data.entitlements.joinguard
        ):
            return

        nickname: hikari.UndefinedOr[str] = hikari.UNDEFINED
        if data.config.general_dehoisting_enabled:
            user = self.app.bot.cache.get_user(user_id)
            if user is None:
                user = await self.app.bot.rest.fetch_user(user_id)

            name = user.username.lstrip("! ")
            if not name:
                name = "dehoisted"

            if name != user.username:
                nickname = name

        self.whitelisted.add(user_id)
        await self.app.bot.rest.add_user_to_guild(
            token, guild, user_id, nickname=nickname
        )
