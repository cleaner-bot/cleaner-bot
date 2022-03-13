import asyncio
from datetime import timedelta
import logging
import typing

import hikari
from hikari.internal.time import utc_datetime
import janus

from cleaner_conf.guild.config import Config
from expirepy import ExpiringSet, ExpiringDict

from ..bot import TheCleaner
from ..shared.event import (
    IActionChallenge,
    IActionNickname,
    IActionAnnouncement,
    IActionDelete,
    IGuildEvent,
    ILog,
)


logger = logging.getLogger(__name__)


class HTTPService:
    main_queue: janus.Queue[IGuildEvent]
    log_queue: asyncio.Queue[ILog]

    def __init__(self, bot: TheCleaner) -> None:
        self.bot = bot
        self.main_queue = janus.Queue()
        self.log_queue = asyncio.Queue()

        self.guild_strikes = ExpiringDict(expires=300)
        self.member_strikes = ExpiringDict(expires=3600)
        self.member_edit = ExpiringDict(expires=10)
        self.challenged_users = ExpiringSet(expires=5)
        self.banned_users = ExpiringSet(expires=60)
        self.deleted_messages = ExpiringSet(expires=60)

    async def ind(self):
        while True:
            ev: IGuildEvent = await self.main_queue.async_q.get()
            if isinstance(ev, IActionChallenge):
                asyncio.create_task(self.run(self.handle_action_challenge(ev)))

            elif isinstance(ev, IActionDelete):
                asyncio.create_task(self.run(self.handle_action_delete(ev)))

            elif isinstance(ev, IActionNickname):
                asyncio.create_task(self.run(self.handle_action_nickname(ev)))

            elif isinstance(ev, IActionAnnouncement):
                asyncio.create_task(self.run(self.handle_action_announcement(ev)))

            elif isinstance(ev, ILog):
                self.log_queue.put_nowait(ev)

            else:
                logger.warning(f"unexpected event received: {ev}")

    async def run(self, coro):
        try:
            await coro
        except Exception as e:
            logger.exception("Error occured during http run", exc_info=e)

    async def handle_action_challenge(self, ev: IActionChallenge):
        can_timeout = ev.can_timeout
        can_role = ev.can_role
        can_kick = ev.can_kick
        if can_timeout or can_role:
            can_due_to_ratelimits = self.member_edit.get(ev.guild_id, 0) < 8
            can_timeout = can_timeout and can_due_to_ratelimits
            can_role = can_role and can_due_to_ratelimits

        user_strikes = self.member_strikes.get(f"{ev.guild_id}-{ev.user_id}", 0)
        guild_strikes = self.guild_strikes.get(ev.guild_id, 0)

        worth = 3
        if ev.block and user_strikes < 2 and guild_strikes < 10:
            worth = 1

        self.member_strikes[f"{ev.guild_id}-{ev.user_id}"] = user_strikes + worth
        self.guild_strikes[ev.guild_id] = guild_strikes + worth

        if ev.block and user_strikes < 2 and guild_strikes < 10:
            return

        strikes = (user_strikes + guild_strikes // 2) / 3
        if guild_strikes >= 30 and ev.can_ban:
            can_timeout = can_role = can_kick = False
        elif (strikes > 6 or guild_strikes >= 10) and (ev.can_ban or can_kick):
            can_timeout = can_role = False
        elif (strikes > 2 or guild_strikes >= 4) and ev.can_role:
            can_timeout = False

        message = "log_challenge_failure"
        if can_timeout or can_role or ev.can_kick or ev.can_ban:
            self.challenged_users.add(f"{ev.guild_id}-{ev.user_id}")

        if can_timeout:
            self.member_edit[ev.guild_id] = self.member_edit.get(ev.guild_id, 0) + 1

            communication_disabled_until = utc_datetime() + timedelta(
                seconds=30 * strikes
            )
            message = "log_challenge_timeout"
            await self.bot.bot.rest.edit_member(
                ev.guild_id,
                ev.user_id,
                communication_disabled_until=communication_disabled_until,
            )

        elif can_role:
            self.member_edit[ev.guild_id] = self.member_edit.get(ev.guild_id, 0) + 1

            message = "log_challenge_role"
            await self.bot.bot.rest.add_role_to_member(
                ev.guild_id, ev.user_id, ev.role_id
            )

        elif can_kick:
            message = "log_challenge_kick"
            await self.bot.bot.rest.kick_user(ev.guild_id, ev.user_id)

        elif ev.can_ban:
            message = "log_challenge_ban"
            await self.bot.bot.rest.ban_user(
                ev.guild_id, ev.user_id, delete_message_days=1
            )
            self.banned_users.add(f"{ev.guild_id}-{ev.user_id}")

        self.log_queue.put_nowait(ILog(ev.guild_id, message, None))

    async def handle_action_delete(self, ev: IActionDelete):
        if ev.message_id in self.deleted_messages:
            return
        elif f"{ev.guild_id}-{ev.user_id}" in self.banned_users:
            return
        self.deleted_messages.add(ev.message_id)
        if ev.can_delete:
            await self.bot.bot.rest.delete_message(ev.channel_id, ev.message_id)

        message = "log_delete_success" if ev.can_delete else "log_delete_failure"
        self.log_queue.put_nowait(ILog(ev.guild_id, message, ev.message))

    async def handle_action_nickname(self, ev: IActionNickname):
        kick = False
        if ev.can_reset:
            current = self.member_edit.get(ev.guild_id, 0) + 1
            self.member_edit[ev.guild_id] = current
            if current >= 8:
                kick = True
                # TODO: can_kick and can_ban
                await self.bot.bot.rest.kick_user(ev.guild_id, ev.user_id)
            else:
                await self.bot.bot.rest.edit_member(ev.guild_id, ev.user_id, nick=None)

        message = "log_nickname_reset_" + ("success" if ev.can_reset else "failure")
        if kick:
            message = "log_nickname_kick"

        self.log_queue.put_nowait(ILog(ev.guild_id, message, None))

    async def handle_action_announcement(self, ev: IActionAnnouncement):
        guild_strikes = self.guild_strikes.get(ev.guild_id, 0)
        if guild_strikes >= 30:
            return
        elif not ev.can_send:
            self.log_queue.put_nowait(
                ILog(ev.guild_id, "log_announcement_failure", None)
            )
            return

        message = await self.bot.bot.rest.create_message(ev.channel_id, ev.announcement)
        if ev.delete_after > 0:
            await asyncio.sleep(ev.delete_after)
            try:
                await message.delete()
            except (hikari.NotFoundError, hikari.ForbiddenError):
                pass

    async def logd(self):
        guilds: dict[int, list[ILog]] = {}
        while True:
            await asyncio.sleep(1)
            while not self.log_queue.empty():
                log = self.log_queue.get_nowait()
                if log.guild_id not in guilds:
                    guilds[log.guild_id] = []
                guilds[log.guild_id].append(log)

            sends = []
            for guild_id, logs in guilds.items():
                referenced_message = None
                length = 0
                for i, log in enumerate(logs):
                    if len(log.message) + 1 + length > 2000:
                        break
                    length += len(log.message) + 1
                    if (
                        referenced_message is None
                        and log.referenced_message is not None
                    ):
                        referenced_message = log.referenced_message
                    i += 1

                guilds[guild_id] = logs[i:]
                message = "\n".join(x.message for x in logs[:i])

                embed = hikari.UNDEFINED
                if referenced_message is not None:
                    embed = (
                        hikari.Embed(
                            description=referenced_message.content, color=0xF43F5E
                        )
                        .set_author(name="Deleted message")
                        .set_footer(
                            text=(
                                f"{referenced_message.author} "
                                f"({referenced_message.author.id})"
                            ),
                            icon=referenced_message.author.make_avatar_url(
                                ext="webp", size=64
                            ),
                        )
                        .add_field(
                            name="Channel",
                            value=(
                                f"<#{referenced_message.channel_id}> "
                                f"({referenced_message.channel_id})"
                            ),
                        )
                    )
                    if referenced_message.stickers:
                        sticker = referenced_message.stickers[0]
                        embed.set_image(sticker.image_url)
                        embed.add_field(
                            name="Sticker", value=f"{sticker.name} ({sticker.id})"
                        )

                config = self.get_config(guild_id)
                channel = 919380927602384926  # TODO: change channel
                if (
                    config is not None
                    and config.logging_enabled
                    and config.logging_channel > 0
                ):
                    channel = config.logging_channel  # TODO: verify channel is in guild

                sends.append(
                    self.bot.bot.rest.create_message(channel, message, embed=embed)
                )

            for guild_id in tuple(guilds.keys()):
                if not guilds[guild_id]:
                    del guilds[guild_id]

            await asyncio.gather(*sends)

    def get_config(self, guild_id: int) -> typing.Optional[Config]:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None
        return conf.get_config(guild_id)
