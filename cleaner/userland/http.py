from __future__ import annotations

import asyncio
import logging
import typing
from collections import defaultdict
from datetime import timedelta

import hikari
from expirepy import ExpiringDict, ExpiringSet
from hikari.internal.time import utc_datetime

from ._types import ConfigType, KernelType, PunishmentEvent
from .helpers.binding import complain_if_none, safe_call
from .helpers.escape import escape_markdown
from .helpers.localization import Message
from .helpers.permissions import DANGEROUS_PERMISSIONS, permissions_for

logger = logging.getLogger(__name__)


class HTTPService:
    _delete_queue: asyncio.Queue[DeleteJob]

    challenged_members: ExpiringSet[str]
    member_strikes: ExpiringDict[str, int]
    guild_strikes: ExpiringDict[int, int]
    member_edits: ExpiringDict[int, int]
    deleted_messages: ExpiringSet[int]
    bulk_delete_ratelimits: ExpiringSet[int]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self._delete_queue = asyncio.Queue()

        self.challenged_members = ExpiringSet(expires=3)
        self.member_strikes = ExpiringDict(expires=60 * 60)
        self.guild_strikes = ExpiringDict(expires=5 * 60)
        self.member_edits = ExpiringDict(expires=10)
        self.deleted_messages = ExpiringSet(expires=60)
        self.bulk_delete_ratelimits = ExpiringSet(expires=3)

        self.kernel.bindings["http:challenge"] = self.challenge
        self.kernel.bindings["http:delete"] = self.delete
        self.kernel.bindings["http:nickname"] = self.nickname
        self.kernel.bindings["http:announcement"] = self.announcement
        self.kernel.bindings["http:channel_ratelimit"] = self.channel_ratelimit
        self.kernel.bindings["http:danger_level"] = self.get_danger_level
        self.kernel.bindings["http:member:create"] = self.on_member_create

        self.tasks = [
            asyncio.create_task(self.delete_task(), name="delete"),
        ]

    def on_unload(self) -> None:
        for task in self.tasks:
            task.cancel()

    async def on_member_create(self, member: hikari.Member) -> None:
        bound_member_id = f"{member.guild_id}-{member.id}"
        try:
            self.challenged_members.remove(bound_member_id)
        except KeyError:
            pass

    async def challenge(
        self,
        member: hikari.Member,
        config: ConfigType,
        block: bool,
        reason: Message,
        yeet_level: int,
    ) -> None:
        # yeet_level explanation
        # 0 = no yeet
        # 1 = only kick/ban
        # 2 = only kick (falling back to ban)
        # 3 = only ban (falling back to kick)

        bound_member_id = f"{member.guild_id}-{member.id}"
        if bound_member_id in self.challenged_members:
            return
        guild = member.get_guild()

        has_admin = has_timeout = has_role = has_kick = has_ban = False
        above_in_role_hierarchy = False
        role = None

        on_member_edit_ratelimit = self.member_edits.get(member.guild_id, 0) >= 8

        if guild is not None:
            me = guild.get_my_member()
            if me is not None:
                my_top_role = me.get_top_role()
                for role in me.get_roles():
                    if role.permissions & hikari.Permissions.ADMINISTRATOR:
                        has_admin = True
                    elif role.permissions & hikari.Permissions.MODERATE_MEMBERS:
                        has_timeout = True
                    elif role.permissions & hikari.Permissions.MANAGE_ROLES:
                        has_role = True
                    elif role.permissions & hikari.Permissions.KICK_MEMBERS:
                        has_kick = True
                    elif role.permissions & hikari.Permissions.BAN_MEMBERS:
                        has_ban = True

                    member_top_role = member.get_top_role()
                    if (
                        my_top_role is not None
                        and member_top_role is not None
                        and my_top_role.position > member_top_role.position
                    ):
                        above_in_role_hierarchy = True

            if (
                config["verification_enabled"]
                and config["punishments_verification_enabled"]
            ):
                role = guild.get_role(int(config["verification_role"]))

            if role and (
                role.permissions & DANGEROUS_PERMISSIONS
                or (role.id in member.role_ids) != config["verification_take_role"]
                or (
                    me is not None
                    and my_top_role is not None
                    and role.position >= my_top_role.position
                )
            ):
                role = None

        danger = self.get_danger_level(member.guild_id, member.id, block)
        logger.debug(
            f"challenge - member={member.id} guild={member.guild_id} danger={danger} "
            f"role={role} perms=(admin={has_admin}/ban={has_ban}/kick={has_kick}/"
            f"role={has_role}/timeout={has_timeout}) "
            f"above_in_role_hierarchy={above_in_role_hierarchy}"
        )
        worth = 1 if danger == 0 and block else 3

        self.member_strikes[bound_member_id] = (
            self.member_strikes.get(bound_member_id, 1) + worth
        )
        self.guild_strikes[member.guild_id] = (
            self.guild_strikes.get(member.guild_id, 0) + worth
        )

        if danger == 0 and block:
            return

        possible_challenges: list[
            typing.Literal["timeout-30s", "timeout-5m", "role", "kick", "ban"]
        ] = []
        if (
            config["punishments_timeout_enabled"]
            and (has_admin or has_timeout)
            and above_in_role_hierarchy
            and not on_member_edit_ratelimit
            and yeet_level == 0
        ):
            possible_challenges.append("timeout-30s")
            possible_challenges.append("timeout-5m")
        if (
            role
            and (has_admin or has_role)
            and above_in_role_hierarchy
            and not on_member_edit_ratelimit
            and yeet_level == 0
        ):
            possible_challenges.append("role")
        if (has_admin or has_kick) and above_in_role_hierarchy and yeet_level != 3:
            possible_challenges.append("kick")
        if (has_admin or has_ban) and above_in_role_hierarchy and yeet_level != 2:
            possible_challenges.append("ban")

        if "kick" in possible_challenges and "ban" in possible_challenges:
            if yeet_level == 2:
                danger -= 50
            elif yeet_level == 3:
                possible_challenges.remove("kick")

        if not possible_challenges:
            logger.debug(f"possible challenges: {possible_challenges}")
            if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
                await safe_call(
                    log(
                        guild if guild is not None else member.guild_id,
                        Message(
                            "log_punishment_failure",
                            {
                                "user": member.id,
                                "name": escape_markdown(str(member.user)),
                            },
                        ),
                        reason,
                        None,
                    )
                )
            return

        if yeet_level:
            danger -= 5

        challenge = possible_challenges[
            max(0, min(len(possible_challenges) - 1, danger - 1 if block else danger))
        ]
        logger.debug(f"possible challenges: {possible_challenges}, chose: {challenge}")

        coro: typing.Awaitable[typing.Any] | None = None
        locale = "en-US" if guild is None else guild.preferred_locale
        if challenge.startswith("timeout-"):
            self.member_edits[member.guild_id] = (
                self.member_edits.get(member.guild_id, 0) + 1
            )

            duration = 30 if challenge == "timeout-30s" else 300
            communication_disabled_until = utc_datetime() + timedelta(seconds=duration)
            coro = member.edit(
                communication_disabled_until=communication_disabled_until,
                reason=reason.translate(self.kernel, locale),
            )

        elif challenge == "role":
            self.member_edits[member.guild_id] = (
                self.member_edits.get(member.guild_id, 0) + 1
            )
            routine = member.remove_role
            if config["verification_take_role"]:
                routine = member.add_role
            assert role is not None, "impossible"
            coro = routine(role, reason=reason.translate(self.kernel, locale))
            await self.kernel.database.hincrby(
                f"guild:{member.guild_id}:verification", str(member.id), 1
            )

        elif challenge == "kick":
            coro = member.kick(reason=reason.translate(self.kernel, locale))

        elif challenge == "ban":
            coro = member.ban(
                reason=reason.translate(self.kernel, locale), delete_message_days=1
            )

        self.challenged_members.add(bound_member_id)

        assert coro is not None, "this should never happen"
        tasks = [coro]

        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            tasks.append(
                safe_call(
                    log(
                        guild if guild is not None else member.guild_id,
                        Message(
                            f"log_punishment_{challenge}",
                            {
                                "user": member.id,
                                "name": escape_markdown(str(member.user)),
                            },
                        ),
                        reason,
                        None,
                    )
                )
            )

        if challenge in ("kick", "ban"):
            submit_challenge = typing.cast(typing.Literal["kick", "ban"], challenge)
            # submit to radar
            if raid_submit := complain_if_none(
                self.kernel.bindings.get("radar:raid:submit"), "radar:raid:submit"
            ):
                tasks.append(safe_call(raid_submit(member, submit_challenge), True))

        if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
            info: PunishmentEvent = {
                "name": "punishment",
                "guild_id": member.guild_id,
                "action": challenge,
            }
            tasks.append(safe_call(track(info), True))

        await asyncio.gather(*tasks)

    async def delete(
        self,
        message_id: int,
        channel_id: int,
        user: hikari.SnowflakeishOr[hikari.User],
        should_log: bool,
        reason: Message | None = None,
        referenced_message: hikari.PartialMessage | None = None,
    ) -> None:
        if message_id in self.deleted_messages:
            return
        self.deleted_messages.add(message_id)

        logger.debug(f"deleting message id={message_id} channel={channel_id}")

        channel = self.kernel.bot.cache.get_guild_channel(channel_id)
        if channel is None:
            thread = self.kernel.bot.cache.get_thread(channel_id)
            if thread is None:
                logger.debug("cant delete, channel/thread is gone")
                return
            channel = self.kernel.bot.cache.get_guild_channel(thread.parent_id)
            if channel is None:
                logger.debug("cant delete, parent channel of thread is gone")
                return

        my_user = self.kernel.bot.cache.get_me()
        assert my_user is not None, "I am None"
        me = self.kernel.bot.cache.get_member(channel.guild_id, my_user)
        if me is None:
            logger.debug("cant delete, I am gone")
            return

        perms = permissions_for(me, channel)

        message_args = {
            "channel": channel_id,
            "user": user.id if isinstance(user, hikari.User) else user,
            "name": escape_markdown(
                str(user)
                if isinstance(user, hikari.User)
                else str(self.kernel.bot.cache.get_user(user))
            ),
        }

        can_delete = (
            perms
            & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_MESSAGES)
            > 0
        )
        tasks: list[typing.Awaitable[typing.Any]] = []
        if should_log and (
            log := complain_if_none(self.kernel.bindings.get("log"), "log")
        ):
            tasks.append(
                safe_call(
                    log(
                        channel.guild_id,
                        Message(
                            "log_delete_success"
                            if can_delete
                            else "log_delete_failure",
                            message_args,
                        ),
                        reason,
                        referenced_message,
                    )
                )
            )

        if can_delete:
            tasks.append(self._delete_queue.put(DeleteJob(message_id, channel_id)))
        else:
            logger.debug("cant delete, no perms")

        if tasks:
            await asyncio.gather(*tasks)

    async def nickname(
        self,
        member: hikari.Member,
        nickname: str | None,
        reason: Message,
    ) -> None:
        guild = self.kernel.bot.cache.get_guild(member.guild_id)
        has_admin = has_nickname = above_in_role_hierarchy = False

        locale = "en-US" if guild is None else guild.preferred_locale

        if guild is not None:
            me = guild.get_my_member()
            if me is not None:
                for role in me.get_roles():
                    if role.permissions & hikari.Permissions.ADMINISTRATOR:
                        has_admin = True
                    elif role.permissions & hikari.Permissions.MANAGE_NICKNAMES:
                        has_nickname = True

                    my_top_role = me.get_top_role()
                    member_top_role = member.get_top_role()
                    if (
                        my_top_role is not None
                        and member_top_role is not None
                        and my_top_role.position > member_top_role.position
                    ):
                        above_in_role_hierarchy = True

        logger.debug(
            f"change nickname user={member}, new={nickname}, "
            f"perms=(admin={has_admin}/change={has_nickname})"
            f"above={above_in_role_hierarchy}"
        )

        can_nickname = above_in_role_hierarchy and (has_admin or has_nickname)
        if can_nickname:
            current = self.member_edits.get(member.guild_id, 0)
            logger.debug(f"nickname uses: {current}/8")
            while current >= 8:
                await asyncio.sleep(10)
                current = self.member_edits.get(member.guild_id, 0)
            self.member_edits[member.guild_id] = current + 1

        coro: typing.Awaitable[typing.Any] | None = None
        name = "failure"
        if can_nickname:
            coro = ignore_not_found(
                member.edit(
                    nickname=nickname, reason=reason.translate(self.kernel, locale)
                )
            )
            name = "success"

        tasks: list[typing.Awaitable[typing.Any]] = []

        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            tasks.append(
                safe_call(
                    log(
                        guild if guild is not None else member.guild_id,
                        Message(
                            f"log_nickname_{name}",
                            {
                                "user": str(member.id),
                                "name": escape_markdown(str(member.user)),
                                "new_name": (
                                    escape_markdown(nickname) if nickname else nickname
                                ),
                            },
                        ),
                        reason,
                        None,
                    )
                )
            )

        if coro is not None:
            tasks.append(coro)

        if tasks:
            await asyncio.gather(*tasks)

    async def announcement(
        self,
        guild_id: int,
        channel_id: int,
        announcement: Message,
        delete_after: float,
    ) -> None:
        danger = self.get_danger_level(guild_id)
        if danger >= 2:
            logger.debug(
                f"suppressed announcement due to danger (channel={channel_id} "
                f"guild={guild_id} danger={danger})"
            )
            return

        my_user = self.kernel.bot.cache.get_me()
        assert my_user is not None, "I am None"
        me = self.kernel.bot.cache.get_member(guild_id, my_user)
        if me is None:
            logger.debug("cant announce, I am gone")
            return

        channel = self.kernel.bot.cache.get_guild_channel(channel_id)
        if channel is None:
            thread = self.kernel.bot.cache.get_thread(channel_id)
            if thread is None:
                logger.debug("cant announce, channel/thread is gone")
                return
            channel = self.kernel.bot.cache.get_guild_channel(thread.parent_id)
            if channel is None:
                logger.debug("cant announce, parent channel of thread is gone")
                return

        perms = permissions_for(me, channel)

        can_send = perms & hikari.Permissions.ADMINISTRATOR > 0
        if not can_send:
            required = (
                hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
            )
            can_send = perms & required == required

        logger.debug(
            f"announcement (can_send={can_send} channel={channel.id} "
            f"guild={channel.guild_id} danger={danger})"
        )

        if not can_send:
            if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
                await safe_call(
                    log(
                        channel.guild_id,
                        Message("log_announcement_failure", {"channel": channel.id}),
                        None,
                        None,
                    ),
                    True,
                )
            return

        guild = channel.get_guild()
        locale = "en-US" if guild is None else guild.preferred_locale
        msg = await self.kernel.bot.rest.create_message(
            channel_id, announcement.translate(self.kernel, locale), user_mentions=True
        )

        if delete_after > 0:
            await asyncio.sleep(delete_after)
            await self.delete(msg.id, channel_id, my_user, False, None, msg)

    async def channel_ratelimit(
        self,
        channel: hikari.GuildTextChannel,
        rate_limit_per_user: int,
    ) -> None:
        guild = channel.get_guild()
        if guild is None:
            logger.debug("cant change ratelimit, guild is gone")
            return
        me = guild.get_my_member()
        if me is None:
            logger.debug("cant change ratelimit, I am gone")
            return

        perms = permissions_for(me, channel)
        can_modify = (
            perms
            & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_CHANNELS)
            > 0
        )

        logger.debug(
            f"change ratelimit (channel={channel.id} guild={channel.guild_id} "
            f"rate_limit_per_user={rate_limit_per_user} can_modify={can_modify})"
        )
        if not can_modify:
            return  # silently ignore because it's probably on purpose

        translated = Message(
            "log_channelratelimit_success",
            {"channel": channel.id, "ratelimit": rate_limit_per_user},
        )
        tasks: list[typing.Awaitable[typing.Any]] = [
            channel.edit(
                rate_limit_per_user=rate_limit_per_user,
                reason=translated.translate(self.kernel, guild.preferred_locale),
            ),
        ]

        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            tasks.append(
                safe_call(
                    log(
                        channel.guild_id if guild is None else guild,
                        translated,
                        None,
                        None,
                    )
                )
            )

        await asyncio.gather(*tasks)

    def get_danger_level(
        self, guild_id: int, member_id: int | None = None, block: bool = False
    ) -> int:
        guild_strikes = self.guild_strikes.get(guild_id, 0)
        user_strikes = 0
        if member_id is not None:
            user_strikes = self.member_strikes.get(f"{guild_id}-{member_id}", 1)

        if block:
            return max(user_strikes // 3, guild_strikes // 12 - 1)
        return max(user_strikes // 3, guild_strikes // 12)

    async def delete_task(self) -> None:
        channels: dict[int, list[int]] = defaultdict(list)
        while True:
            await asyncio.sleep(1)
            while not self._delete_queue.empty():
                delete = self._delete_queue.get_nowait()
                channels[delete.channel_id].append(delete.message_id)

            futures = []
            for channel_id, deletes in tuple(channels.items()):
                if len(deletes) <= 3:
                    for message_id in deletes:
                        futures.append(
                            self.kernel.bot.rest.delete_message(channel_id, message_id)
                        )
                    logger.debug(f"deleted {len(deletes)} messages in {channel_id}")
                    del channels[channel_id]

                elif channel_id not in self.bulk_delete_ratelimits:
                    self.bulk_delete_ratelimits.add(channel_id)
                    futures.append(
                        self.kernel.bot.rest.delete_messages(channel_id, deletes[:100])
                    )
                    logger.debug(
                        f"bulk deleted {min(100, len(deletes))} "
                        f"messages in {channel_id}"
                    )
                    deletes = deletes[100:]

                    if deletes:
                        channels[channel_id] = deletes
                    else:
                        del channels[channel_id]

            for coro in futures:
                asyncio.create_task(ignore_not_found(coro), name="x.deletemsg")


async def ignore_not_found(coro: typing.Awaitable[typing.Any]) -> None:
    try:
        await coro
    except hikari.NotFoundError:
        pass
    except Exception as e:
        logger.exception("exception occured", exc_info=e)


class DeleteJob(typing.NamedTuple):
    message_id: int
    channel_id: int
