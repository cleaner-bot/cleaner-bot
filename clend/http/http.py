import asyncio
from datetime import datetime, timedelta
import logging
import random
import typing

import hikari
from hikari.internal.time import utc_datetime
import janus

from cleaner_conf.guild import GuildConfig, GuildEntitlements
from cleaner_i18n.translate import Message, translate
from expirepy import ExpiringSet, ExpiringDict

from .likely_phishing import is_likely_phishing, report_phishing
from ..bot import TheCleaner
from ..shared.channel_perms import permissions_for
from ..shared.event import (
    IActionChallenge,
    IActionChannelRatelimit,
    IActionNickname,
    IActionAnnouncement,
    IActionDelete,
    IGuildEvent,
    ILog,
)


logger = logging.getLogger(__name__)
REQUIRED_TO_SEND = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
VOTING_REMINDER_COOLDOWN = 60 * 60 * 24 * 3


def format_log(log: ILog, locale: str):
    time_string = log.created_at.strftime("%H:%M:%S")
    reason = ""
    if log.reason:
        reason = f"` Reason ` {log.reason.translate(locale)}\n"
    return f"`{time_string}` {log.message.translate(locale)}\n{reason}"


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

        self.guild_voting_reminder = ExpiringSet(expires=VOTING_REMINDER_COOLDOWN)

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

            elif isinstance(ev, IActionChannelRatelimit):
                asyncio.create_task(self.run(self.handle_action_channelratelimit(ev)))

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

        user_strikes += worth
        guild_strikes += worth

        if ev.block and user_strikes < 3 and guild_strikes < 13:
            return

        strikes = (user_strikes + guild_strikes // 2) / 3
        if (guild_strikes >= 30 or user_strikes > 12) and ev.can_ban:
            can_timeout = can_role = can_kick = False
        elif (strikes > 6 or guild_strikes >= 10) and (ev.can_ban or can_kick):
            can_timeout = can_role = False
        elif (strikes > 2 or guild_strikes >= 4) and ev.can_role:
            can_timeout = False

        message = "log_challenge_failure"
        if can_timeout or can_role or ev.can_kick or ev.can_ban:
            self.challenged_users.add(f"{ev.guild_id}-{ev.user_id}")

        coro: typing.Coroutine[typing.Any, typing.Any, typing.Any] | None = None

        guild = self.bot.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        if can_timeout:
            self.member_edit[ev.guild_id] = self.member_edit.get(ev.guild_id, 0) + 1

            communication_disabled_until = utc_datetime() + timedelta(
                seconds=30 * strikes
            )
            message = "log_challenge_timeout"
            coro = self.bot.bot.rest.edit_member(
                ev.guild_id,
                ev.user_id,
                communication_disabled_until=communication_disabled_until,
                reason=ev.reason.translate(locale),
            )

        elif can_role:
            self.member_edit[ev.guild_id] = self.member_edit.get(ev.guild_id, 0) + 1

            message = "log_challenge_role"
            routine = self.bot.bot.rest.remove_role_from_member
            if ev.take_role:
                routine = self.bot.bot.rest.add_role_to_member
            coro = routine(
                ev.guild_id,
                ev.user_id,
                ev.role_id,
                reason=ev.reason.translate(locale),
            )

            database = self.bot.database
            await database.sadd(f"guild:{ev.guild_id}:challenged", (ev.user_id,))

        elif can_kick:
            message = "log_challenge_kick"
            coro = self.bot.bot.rest.kick_user(
                ev.guild_id,
                ev.user_id,
                reason=ev.reason.translate(locale),
            )

        elif ev.can_ban:
            message = "log_challenge_ban"
            coro = self.bot.bot.rest.ban_user(
                ev.guild_id,
                ev.user_id,
                delete_message_days=1,
                reason=ev.reason.translate(locale),
            )
            self.banned_users.add(f"{ev.guild_id}-{ev.user_id}")

        translated = Message(message, {"user": ev.user_id})
        self.log_queue.put_nowait(
            ILog(ev.guild_id, translated, datetime.utcnow(), ev.reason)
        )
        self.put_in_metrics_queue(
            {
                "name": "challenge",
                "guild": ev.guild_id,
                "action": message.split("_")[-1],
                "info": ev.info,
            }
        )
        if coro is not None:
            await coro

    async def handle_action_delete(self, ev: IActionDelete):
        if ev.message_id in self.deleted_messages:
            return
        elif f"{ev.guild_id}-{ev.user_id}" in self.banned_users:
            return
        self.deleted_messages.add(ev.message_id)
        coro: typing.Coroutine[typing.Any, typing.Any, typing.Any] | None = None
        if ev.can_delete:
            coro = self.bot.bot.rest.delete_message(ev.channel_id, ev.message_id)

        message = "log_delete_success" if ev.can_delete else "log_delete_failure"

        translated = Message(message, {"user": ev.user_id, "channel": ev.channel_id})
        self.log_queue.put_nowait(
            ILog(ev.guild_id, translated, datetime.utcnow(), ev.reason, ev.message)
        )
        self.put_in_metrics_queue(
            {
                "name": "delete",
                "guild": ev.guild_id,
                "action": message.split("_")[-1],
                "info": ev.info,
            }
        )
        if coro is not None:
            try:
                await coro
            except hikari.NotFoundError:
                pass

        if ev.message is not None and is_likely_phishing(ev):
            guild_strikes = self.guild_strikes.get(ev.guild_id, 0)
            if guild_strikes >= 30:
                return
            await report_phishing(ev, self.bot)

    async def handle_action_nickname(self, ev: IActionNickname):
        coro: typing.Coroutine[typing.Any, typing.Any, typing.Any] | None = None
        message = "log_nickname_reset_failure"

        guild = self.bot.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        if ev.can_reset:
            current = self.member_edit.get(ev.guild_id, 0) + 1
            self.member_edit[ev.guild_id] = current
            if current >= 8:
                if ev.can_kick:
                    coro = self.bot.bot.rest.kick_user(
                        ev.guild_id, ev.user_id, reason=ev.reason.translate(locale)
                    )
                    message = "log_nickname_reset_kick"
                elif ev.can_ban:
                    coro = self.bot.bot.rest.ban_user(
                        ev.guild_id, ev.user_id, reason=ev.reason.translate(locale)
                    )
                    message = "log_nickname_reset_ban"
                else:
                    message = "log_nickname_failure"
            else:
                message = "log_nickname_reset_success"
                coro = self.bot.bot.rest.edit_member(
                    ev.guild_id,
                    ev.user_id,
                    nickname=None,
                    reason=ev.reason.translate(locale),
                )

        translated = Message(message, {"user": ev.user_id})
        self.log_queue.put_nowait(
            ILog(ev.guild_id, translated, datetime.utcnow(), ev.reason)
        )
        self.put_in_metrics_queue(
            {
                "name": "nickname",
                "guild": ev.guild_id,
                "action": "_".join(message.split("_")[2:]),
                "info": ev.info,
            }
        )
        if coro is not None:
            await coro

    async def handle_action_announcement(self, ev: IActionAnnouncement):
        guild_strikes = self.guild_strikes.get(ev.guild_id, 0)
        if guild_strikes >= 30:
            return
        elif not ev.can_send:
            translated = Message("log_announcement_failure", {"channel": ev.channel_id})
            self.log_queue.put_nowait(ILog(ev.guild_id, translated, datetime.utcnow()))
            return

        guild = self.bot.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        announcement = ev.announcement.translate(locale)
        message = await self.bot.bot.rest.create_message(ev.channel_id, announcement)
        if ev.delete_after > 0:
            await asyncio.sleep(ev.delete_after)
            try:
                await message.delete()
            except (hikari.NotFoundError, hikari.ForbiddenError):
                pass

    async def handle_action_channelratelimit(self, ev: IActionChannelRatelimit):
        if not ev.can_modify:
            return  # silently ignore

        guild = self.bot.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        translated = Message(
            "log_channelratelimit_success",
            {"channel": ev.channel_id, "ratelimit": ev.ratelimit},
        )
        self.log_queue.put_nowait(ILog(ev.guild_id, translated, datetime.utcnow()))

        await self.bot.bot.rest.edit_channel(
            ev.channel_id,
            rate_limit_per_user=ev.ratelimit,
            reason=translated.translate(locale),
        )

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
                guild = self.bot.bot.cache.get_guild(guild_id)
                locale = "en-US" if guild is None else guild.preferred_locale

                referenced_message = None
                result = []
                length = 0
                for log_index, log in enumerate(logs):
                    formatted_log = format_log(log, locale)
                    log_length = len(formatted_log)
                    if log_length + length > 2000:
                        break
                    length += log_length
                    if (
                        referenced_message is None
                        and log.referenced_message is not None
                    ):
                        referenced_message = log.referenced_message
                    result.append(formatted_log)

                guilds[guild_id] = logs[log_index + 1 :]
                message = "".join(result)

                embed = hikari.UNDEFINED
                if referenced_message is not None:
                    embed = (
                        hikari.Embed(
                            description=referenced_message.content, color=0xF43F5E
                        )
                        .set_author(name=translate(locale, "log_embed_deleted"))
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
                            name=translate(locale, "log_embed_channel"),
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
                            name=translate(locale, "log_embed_sticker"),
                            value=f"{sticker.name} ({sticker.id})",
                        )

                config = self.get_config(guild_id)
                entitlements = self.get_entitlements(guild_id)
                channel_id = fallback_id = 963043115730608188

                can_send_embed = True
                if (
                    config is not None
                    and config.logging_enabled
                    and int(config.logging_channel) > 0
                ):
                    the_channel_id = int(config.logging_channel)
                    guild = self.bot.bot.cache.get_guild(guild_id)
                    if guild is not None:
                        me = guild.get_my_member()
                        if me is not None:
                            channel = guild.get_channel(the_channel_id)
                            if channel is not None and isinstance(
                                channel, hikari.TextableGuildChannel
                            ):
                                my_perms = permissions_for(me, channel)
                                if my_perms & hikari.Permissions.ADMINISTRATOR:
                                    channel_id = the_channel_id
                                elif my_perms & REQUIRED_TO_SEND == REQUIRED_TO_SEND:
                                    channel_id = the_channel_id
                                    if my_perms & hikari.Permissions.EMBED_LINKS == 0:
                                        can_send_embed = False

                embeds = []
                if can_send_embed:
                    if embed is not hikari.UNDEFINED:
                        if channel_id == fallback_id:
                            guild = self.bot.bot.cache.get_guild(guild_id)
                            if guild is None:
                                embed.add_field("Guild", guild_id)
                            else:
                                embed.add_field("Guild", f"{guild.name} ({guild.id})")

                        embeds.append(embed)

                    if (
                        (entitlements is None or entitlements.plan == 0)
                        and random.random() < 0.05
                        and guild_id not in self.guild_voting_reminder
                    ):
                        embed = hikari.Embed(
                            title=translate(locale, "log_vote_title"),
                            description=translate(locale, "log_vote_description"),
                            color=0x6366F1,
                        ).set_footer(text=translate(locale, "log_vote_footer"))
                        embeds.append(embed)
                        self.guild_voting_reminder.add(guild_id)

                sends.append(
                    self.bot.bot.rest.create_message(
                        channel_id,
                        message,
                        embeds=embeds if embeds else hikari.UNDEFINED,
                    )
                )

            if (
                entitlements.logging_downloads >= entitlements.plan
                and config.logging_downloads_enabled
            ):
                guildlog = self.bot.extensions.get("clend.guildlog", None)
                if guildlog is None:
                    logger.warning("unable to find clend.guildlog extension")
                    return None
                else:
                    for log in logs[:log_index]:
                        guildlog.queue.put_nowait(log)

            for guild_id in tuple(guilds.keys()):
                if not guilds[guild_id]:
                    del guilds[guild_id]

            await asyncio.gather(*sends)

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

    def put_in_metrics_queue(self, item):
        metrics = self.bot.extensions.get("clend.metrics")
        if metrics is None:
            logger.warning("unable to get metrics queue")
            return
        metrics.queue.put_nowait(item)
