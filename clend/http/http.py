from __future__ import annotations

import asyncio
import logging
import random
import typing
from datetime import datetime, timedelta

import hikari
import janus
from cleaner_i18n import Message, translate
from expirepy import ExpiringDict, ExpiringSet
from hikari.internal.time import utc_datetime

from ..app import TheCleanerApp
from ..shared.channel_perms import permissions_for
from ..shared.event import (
    IActionAnnouncement,
    IActionChallenge,
    IActionChannelRatelimit,
    IActionDelete,
    IActionNickname,
    IGuildEvent,
    ILog,
)
from ..shared.protect import protected_call
from .likely_phishing import is_likely_phishing, report_phishing

logger = logging.getLogger(__name__)
REQUIRED_TO_SEND = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
VOTING_REMINDER_COOLDOWN = 60 * 60 * 24 * 3


def format_log(log: ILog, locale: str) -> str:
    time_string = log.created_at.strftime("%H:%M:%S")
    reason = ""
    if log.reason:
        reason = f"` Reason ` {log.reason.translate(locale)}\n"
    return f"`{time_string}` {log.message.translate(locale)}\n{reason}"


async def ignore_not_found_exception_wrapper(
    coro: typing.Coroutine[None, None, typing.Any]
) -> None:
    try:
        await coro
    except hikari.NotFoundError:
        pass


class HTTPService:
    main_queue: janus.Queue[IGuildEvent]
    log_queue: asyncio.Queue[ILog]
    delete_queue: asyncio.Queue[IActionDelete]

    guild_strikes: ExpiringDict[int, int]
    member_strikes: ExpiringDict[str, int]
    member_edit: ExpiringDict[int, int]
    challenged_users: ExpiringSet[str]
    banned_users: ExpiringSet[str]
    deleted_messages: ExpiringSet[int]
    bulk_delete_cooldown: ExpiringSet[int]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.main_queue = janus.Queue()
        self.log_queue = asyncio.Queue()
        self.delete_queue = asyncio.Queue()

        self.guild_strikes = ExpiringDict(expires=300)
        self.member_strikes = ExpiringDict(expires=3600)
        self.member_edit = ExpiringDict(expires=10)
        self.challenged_users = ExpiringSet(expires=5)
        self.banned_users = ExpiringSet(expires=60)
        self.deleted_messages = ExpiringSet(expires=60)
        self.bulk_delete_cooldown = ExpiringSet(expires=3)

    async def ind(self) -> None:
        while True:
            ev: IGuildEvent = await self.main_queue.async_q.get()
            if isinstance(ev, IActionChallenge):
                asyncio.create_task(protected_call(self.handle_action_challenge(ev)))

            elif isinstance(ev, IActionDelete):
                asyncio.create_task(protected_call(self.handle_action_delete(ev)))

            elif isinstance(ev, IActionNickname):
                asyncio.create_task(protected_call(self.handle_action_nickname(ev)))

            elif isinstance(ev, IActionAnnouncement):
                asyncio.create_task(protected_call(self.handle_action_announcement(ev)))

            elif isinstance(ev, IActionChannelRatelimit):
                asyncio.create_task(
                    protected_call(self.handle_action_channelratelimit(ev))
                )

            elif isinstance(ev, ILog):
                self.log_queue.put_nowait(ev)

            else:
                logger.warning(f"unexpected event received: {ev}")

    async def handle_action_challenge(self, ev: IActionChallenge) -> None:
        if f"{ev.guild_id}-{ev.user.id}" in self.challenged_users:
            return

        can_timeout = ev.can_timeout
        can_role = ev.can_role
        can_kick = ev.can_kick
        if can_timeout or can_role:
            can_due_to_ratelimits = self.member_edit.get(ev.guild_id, 0) < 8
            can_timeout = can_timeout and can_due_to_ratelimits
            can_role = can_role and can_due_to_ratelimits

        user_strikes = self.member_strikes.get(f"{ev.guild_id}-{ev.user.id}", 0)
        guild_strikes = self.guild_strikes.get(ev.guild_id, 0)

        worth = 3
        if ev.block and user_strikes < 2 and guild_strikes < 10:
            worth = 1

        self.member_strikes[f"{ev.guild_id}-{ev.user.id}"] = user_strikes + worth
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
            self.challenged_users.add(f"{ev.guild_id}-{ev.user.id}")

        coro: typing.Coroutine[typing.Any, typing.Any, typing.Any] | None = None

        guild = self.app.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        if can_timeout:
            self.member_edit[ev.guild_id] = self.member_edit.get(ev.guild_id, 0) + 1

            communication_disabled_until = utc_datetime() + timedelta(
                seconds=30 * strikes
            )
            message = "log_challenge_timeout"
            coro = self.app.bot.rest.edit_member(
                ev.guild_id,
                ev.user.id,
                communication_disabled_until=communication_disabled_until,
                reason=ev.reason.translate(locale),
            )

        elif can_role:
            self.member_edit[ev.guild_id] = self.member_edit.get(ev.guild_id, 0) + 1

            message = "log_challenge_role"
            routine = self.app.bot.rest.remove_role_from_member
            if ev.take_role:
                routine = self.app.bot.rest.add_role_to_member
            coro = routine(
                ev.guild_id,
                ev.user.id,
                ev.role_id,
                reason=ev.reason.translate(locale),
            )

            database = self.app.database
            await database.sadd(f"guild:{ev.guild_id}:challenged", (ev.user.id,))

        elif can_kick:
            message = "log_challenge_kick"
            coro = self.app.bot.rest.kick_user(
                ev.guild_id,
                ev.user.id,
                reason=ev.reason.translate(locale),
            )

        elif ev.can_ban:
            message = "log_challenge_ban"
            coro = self.app.bot.rest.ban_user(
                ev.guild_id,
                ev.user.id,
                delete_message_days=1,
                reason=ev.reason.translate(locale),
            )
            self.banned_users.add(f"{ev.guild_id}-{ev.user.id}")

        translated = Message(message, {"user": ev.user.id, "name": str(ev.user)})
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

    async def handle_action_delete(self, ev: IActionDelete) -> None:
        if ev.message_id in self.deleted_messages:
            return
        elif f"{ev.guild_id}-{ev.user.id}" in self.banned_users:
            return
        self.deleted_messages.add(ev.message_id)

        message = "log_delete_success" if ev.can_delete else "log_delete_failure"

        translated = Message(
            message,
            {"user": ev.user.id, "channel": ev.channel_id, "name": str(ev.user)},
        )
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

        if ev.can_delete:
            self.delete_queue.put_nowait(ev)

        if ev.message is not None and is_likely_phishing(ev):
            guild_strikes = self.guild_strikes.get(ev.guild_id, 0)
            if guild_strikes >= 30:
                return
            await report_phishing(ev, self.app)

    async def handle_action_nickname(self, ev: IActionNickname) -> None:
        coro: typing.Coroutine[typing.Any, typing.Any, typing.Any] | None = None
        message = "log_nickname_reset_failure"

        guild = self.app.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        if ev.can_change:
            current = self.member_edit.get(ev.guild_id, 0) + 1
            self.member_edit[ev.guild_id] = current
            if current >= 8:
                if ev.can_kick:
                    coro = self.app.bot.rest.kick_user(
                        ev.guild_id, ev.user.id, reason=ev.reason.translate(locale)
                    )
                    message = "log_nickname_kick"
                elif ev.can_ban:
                    coro = self.app.bot.rest.ban_user(
                        ev.guild_id, ev.user.id, reason=ev.reason.translate(locale)
                    )
                    message = "log_nickname_ban"
                else:
                    message = "log_nickname_failure"
            else:
                message = "log_nickname_success"
                coro = self.app.bot.rest.edit_member(
                    ev.guild_id,
                    ev.user.id,
                    nickname=ev.nickname,
                    reason=ev.reason.translate(locale),
                )

        translated = Message(
            message, {"user": ev.user.id, "name": str(ev.user), "new_name": ev.nickname}
        )
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

    async def handle_action_announcement(self, ev: IActionAnnouncement) -> None:
        guild_strikes = self.guild_strikes.get(ev.guild_id, 0)
        if guild_strikes >= 30:
            return
        elif not ev.can_send:
            translated = Message("log_announcement_failure", {"channel": ev.channel_id})
            self.log_queue.put_nowait(ILog(ev.guild_id, translated, datetime.utcnow()))
            return

        guild = self.app.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        announcement = ev.announcement.translate(locale)
        message = await self.app.bot.rest.create_message(ev.channel_id, announcement)
        if ev.delete_after > 0:
            await asyncio.sleep(ev.delete_after)
            me = self.app.bot.cache.get_me()
            assert me, "me is None"
            self.delete_queue.put_nowait(
                IActionDelete(
                    ev.guild_id,
                    me,
                    ev.channel_id,
                    message.id,
                    True,
                    None,
                    ev.announcement,
                    None,
                )
            )

    async def handle_action_channelratelimit(self, ev: IActionChannelRatelimit) -> None:
        if not ev.can_modify:
            return  # silently ignore

        guild = self.app.bot.cache.get_guild(ev.guild_id)
        locale = "en-US" if guild is None else guild.preferred_locale

        translated = Message(
            "log_channelratelimit_success",
            {"channel": ev.channel_id, "ratelimit": ev.ratelimit},
        )
        self.log_queue.put_nowait(ILog(ev.guild_id, translated, datetime.utcnow()))

        await self.app.bot.rest.edit_channel(
            ev.channel_id,
            rate_limit_per_user=ev.ratelimit,
            reason=translated.translate(locale),
        )

    async def logd(self) -> None:
        guilds: dict[int, list[ILog]] = {}
        bot_id = self.app.store.get_bot_id()
        if bot_id is None:
            raise RuntimeError("no bot id available")

        while True:
            await asyncio.sleep(1)
            while not self.log_queue.empty():
                log = self.log_queue.get_nowait()
                if log.guild_id not in guilds:
                    guilds[log.guild_id] = []
                guilds[log.guild_id].append(log)

            sends = []
            for guild_id, logs in guilds.items():
                guild = self.app.bot.cache.get_guild(guild_id)
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

                embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED
                if referenced_message is not None:
                    embed = (
                        hikari.Embed(
                            description=referenced_message.content, color=0xF43F5E
                        )
                        .set_author(name=translate(locale, "log_embed_deleted"))
                        .add_field(
                            name=translate(locale, "log_embed_channel"),
                            value=(
                                f"<#{referenced_message.channel_id}> "
                                f"({referenced_message.channel_id})"
                            ),
                        )
                    )
                    if referenced_message.author:
                        embed.set_footer(
                            text=(
                                f"{referenced_message.author} "
                                f"({referenced_message.author.id})"
                            ),
                            icon=referenced_message.author.make_avatar_url(
                                ext="webp", size=64
                            ),
                        )
                    if referenced_message.stickers:
                        sticker = referenced_message.stickers[0]
                        embed.set_image(sticker.image_url)
                        embed.add_field(
                            name=translate(locale, "log_embed_sticker"),
                            value=f"{sticker.name} ({sticker.id})",
                        )

                data = self.app.store.get_data(guild_id)
                channel_id = fallback_id = 963043115730608188

                can_send_embed = False
                if (
                    data is not None
                    and data.config.logging_enabled
                    and int(data.config.logging_channel) > 0
                ):
                    the_channel_id = int(data.config.logging_channel)
                    guild = self.app.bot.cache.get_guild(guild_id)
                    if guild is not None:
                        me = guild.get_my_member()
                        if me is not None and me.communication_disabled_until() is None:
                            channel = guild.get_channel(the_channel_id)
                            if channel is not None and isinstance(
                                channel, hikari.TextableGuildChannel
                            ):
                                my_perms = permissions_for(me, channel)
                                if my_perms & hikari.Permissions.ADMINISTRATOR:
                                    channel_id = the_channel_id
                                    can_send_embed = True
                                elif my_perms & REQUIRED_TO_SEND == REQUIRED_TO_SEND:
                                    channel_id = the_channel_id
                                    if my_perms & hikari.Permissions.EMBED_LINKS:
                                        can_send_embed = True

                if channel_id == fallback_id:
                    can_send_embed = True

                embeds: list[hikari.Embed] = []
                if can_send_embed:
                    if channel_id == fallback_id:
                        if embed is hikari.UNDEFINED:
                            embed = hikari.Embed()
                        guild = self.app.bot.cache.get_guild(guild_id)
                        if guild is None:
                            embed.add_field("Guild", str(guild_id))
                        else:
                            embed.add_field("Guild", f"{guild.name} ({guild.id})")

                    if embed is not hikari.UNDEFINED:
                        embeds.append(embed)

                    if (
                        (data is None or data.entitlements.plan == 0)
                        and random.random() < 0.05
                        and not await self.app.database.exists(
                            (f"guild:{guild_id}:logging:voting-reminder",)
                        )
                    ):
                        integrations = []
                        integrations.append(
                            (
                                "Top.gg",
                                f"https://top.gg/bot/{bot_id}/vote?guild={guild_id}",
                            )
                        )
                        embed = hikari.Embed(
                            title=translate(locale, "log_vote_title"),
                            description=(
                                translate(locale, "log_vote_description")
                                + "\n\n"
                                + " ".join(
                                    "["
                                    + translate(
                                        locale, "log_vote_integration", name=name
                                    )
                                    + f"]({url})"
                                    for name, url in integrations
                                )
                            ),
                            color=0x6366F1,
                        ).set_footer(text=translate(locale, "log_vote_footer"))
                        embeds.append(embed)
                        await self.app.database.set(
                            f"guild:{guild_id}:logging:voting-reminder",
                            "1",
                            ex=VOTING_REMINDER_COOLDOWN,
                        )

                sends.append(
                    self.app.bot.rest.create_message(
                        channel_id,
                        message,
                        embeds=embeds if embeds else hikari.UNDEFINED,
                    )
                )

                if (
                    data is not None
                    and data.entitlements.plan >= data.entitlements.logging_downloads
                    and data.config.logging_downloads_enabled
                ):
                    guildlog = self.app.extensions.get("clend.guildlog", None)
                    if guildlog is None:
                        logger.warning("unable to find clend.guildlog extension")
                        return None
                    else:
                        for log in logs[: log_index + 1]:
                            guildlog.queue.put_nowait(log)

            for guild_id in tuple(guilds.keys()):
                if not guilds[guild_id]:
                    del guilds[guild_id]

            await asyncio.gather(*sends)

    async def deleted(self) -> None:
        channels: dict[int, list[IActionDelete]] = {}
        while True:
            await asyncio.sleep(1)
            futures = []
            while not self.delete_queue.empty():
                delete = self.delete_queue.get_nowait()
                if f"{delete.guild_id}-{delete.user.id}" in self.banned_users:
                    continue
                if delete.channel_id not in channels:
                    channels[delete.channel_id] = []
                channels[delete.channel_id].append(delete)

            for channel_id, deletes in tuple(channels.items()):
                if len(deletes) <= 3:
                    for delete in deletes:
                        futures.append(
                            self.app.bot.rest.delete_message(
                                channel_id, delete.message_id
                            )
                        )
                    logger.debug(f"deleted {len(deletes)} messages")
                    deletes.clear()
                elif channel_id not in self.bulk_delete_cooldown:
                    self.bulk_delete_cooldown.add(channel_id)
                    messages = [x.message_id for x in deletes[:100]]
                    futures.append(
                        self.app.bot.rest.delete_messages(channel_id, messages)
                    )
                    logger.debug(f"bulk deleted {len(deletes)} messages")
                    deletes = deletes[100:]

                if not deletes:
                    del channels[channel_id]

            for coro in futures:
                asyncio.create_task(ignore_not_found_exception_wrapper(coro))

    def put_in_metrics_queue(self, item: typing.Any) -> None:
        metrics = self.app.extensions.get("clend.metrics")
        if metrics is None:
            logger.warning("unable to get metrics queue")
            return
        metrics.queue.put_nowait(item)
