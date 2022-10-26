from __future__ import annotations

import asyncio
import logging
import random
import typing
from collections import defaultdict
from datetime import datetime

import hikari
from hikari.internal.time import utc_datetime

from ._types import EntitlementsType, KernelType
from .helpers.binding import complain_if_none, safe_call
from .helpers.duration import duration_to_text
from .helpers.embedize import embedize_guild, embedize_user
from .helpers.escape import escape_markdown
from .helpers.localization import Message
from .helpers.permissions import permissions_for
from .helpers.settings import get_config, get_entitlements

logger = logging.getLogger(__name__)
SYSTEM_LOGS = 963076090056822784
FALLBACK_LOGS = 963076110202064977  # 963043115730608188
REQUIRED_TO_SEND: typing.Final = (
    hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
)
VOTING_REMINDER_COOLDOWN: typing.Final = 60 * 60 * 24 * 3


class LogService:
    _log_queue: asyncio.Queue[LogJob]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["log"] = self.log
        self.kernel.bindings["log:member:create"] = self.member_create
        self.kernel.bindings["log:member:delete"] = self.member_delete
        self.kernel.bindings["log:guild:join"] = self.guild_join
        self.kernel.bindings["log:guild:leave"] = self.guild_leave
        self.kernel.bindings["log:raid:ongoing"] = self.raid_ongoing
        self.kernel.bindings["log:raid:complete"] = self.raid_complete

        self._log_queue = asyncio.Queue()
        self.tasks = [
            asyncio.create_task(self.logging_task(), name="logging"),
        ]

    def on_unload(self) -> None:
        for task in self.tasks:
            task.cancel()

    async def member_create(self, member: hikari.Member) -> None:
        logger.debug(f"user {member!s} ({member.id}) joined {member.guild_id}")
        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            age = utc_datetime() - member.created_at
            message = Message(
                "components_log_join",
                {
                    "user": member.id,
                    "name": escape_markdown(str(member.user)),
                    "age": duration_to_text(int(age.total_seconds()), separator=" ")
                    if age.days < 3
                    else f"{age.days}d",
                },
            )
            await safe_call(log(member.guild_id, message, None, None))

    async def member_delete(self, guild_id: int, user_id: int) -> None:
        logger.debug(f"user {user_id} left {guild_id}")
        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            user = self.kernel.bot.cache.get_user(user_id)
            if user is None:
                try:
                    user = await self.kernel.bot.rest.fetch_user(user_id)
                except hikari.NotFoundError:
                    pass

            message = Message(
                "components_log_leave",
                {
                    "user": user_id,
                    "name": escape_markdown(str(user)) if user is not None else "?",
                },
            )
            await safe_call(log(guild_id, message, None, None))

    async def raid_ongoing(
        self,
        guild_id: int,
        start_time: datetime,
        kicks: int,
        bans: int,
    ) -> None:
        logger.debug(
            f"raid ongoing guild={guild_id} {start_time} "
            f"--- so far: kicks={kicks} bans={bans}"
        )

        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            message = Message(
                "log_raid_ongoing",
                {
                    "start": int(start_time.timestamp()),
                    "kicks": kicks,
                    "bans": bans,
                },
            )
            await safe_call(log(guild_id, message, None, None))

        guild = self.kernel.bot.cache.get_guild(guild_id)
        if guild is None:
            return

        owner = self.kernel.bot.cache.get_user(guild.owner_id)
        if owner is None:
            owner = await self.kernel.bot.rest.fetch_user(guild.owner_id)

        await self.kernel.bot.rest.create_message(
            SYSTEM_LOGS,
            f"Guild is being raided!\n"
            f"Raid started at: <t:{int(start_time.timestamp())}:T>\n"
            f"Actions (so far): {bans} bans and {kicks} kicks",
            embeds=[
                await embedize_guild(guild, self.kernel.bot, None, owner),
                embedize_user(owner),
            ],
        )

    async def raid_complete(
        self,
        guild_id: int,
        start_time: datetime,
        end_time: datetime,
        kicks: int,
        bans: int,
    ) -> None:
        logger.debug(
            f"raid complete guild={guild_id} {start_time} --> {end_time} "
            f"kicks={kicks} bans={bans}"
        )

        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            message = Message(
                "log_raid_complete",
                {
                    "start": int(start_time.timestamp()),
                    "end": int(end_time.timestamp()),
                    "kicks": kicks,
                    "bans": bans,
                },
            )
            await safe_call(log(guild_id, message, None, None))

        guild = self.kernel.bot.cache.get_guild(guild_id)
        if guild is None:
            return

        owner = self.kernel.bot.cache.get_user(guild.owner_id)
        if owner is None:
            owner = await self.kernel.bot.rest.fetch_user(guild.owner_id)

        await self.kernel.bot.rest.create_message(
            SYSTEM_LOGS,
            f"Guild was raided!\n"
            f"Raid started at: <t:{int(start_time.timestamp())}:T>\n"
            f"Raid stopped at: <t:{int(end_time.timestamp())}:T>\n"
            f"Actions: {bans} bans and {kicks} kicks",
            embeds=[
                await embedize_guild(guild, self.kernel.bot, None, owner),
                embedize_user(owner),
            ],
        )

    async def guild_join(
        self, guild: hikari.GatewayGuild, entitlements: EntitlementsType
    ) -> None:
        owner = self.kernel.bot.cache.get_user(guild.owner_id)
        if owner is None:
            owner = await self.kernel.bot.rest.fetch_user(guild.owner_id)

        total = len(self.kernel.bot.cache.get_guilds_view())
        await self.kernel.bot.rest.create_message(
            SYSTEM_LOGS,
            f"Joined guild. Total guilds: {total}",
            embeds=[
                await embedize_guild(guild, self.kernel.bot, entitlements, owner),
                embedize_user(owner),
            ],
        )

    async def guild_leave(
        self,
        guild_id: int,
        guild: hikari.GatewayGuild | None,
        entitlements: EntitlementsType,
    ) -> None:
        total = len(self.kernel.bot.cache.get_guilds_view())

        if guild is None:
            await self.kernel.bot.rest.create_message(
                SYSTEM_LOGS,
                f"Left uncached guild. Total guilds: {total}\n" f"Guild id: {guild_id}",
            )
            return

        owner = self.kernel.bot.cache.get_user(guild.owner_id)
        if owner is None:
            owner = await self.kernel.bot.rest.fetch_user(guild.owner_id)
            # no idea why this is private
            self.kernel.bot.cache._set_user(owner)  # type: ignore

        await self.kernel.bot.rest.create_message(
            SYSTEM_LOGS,
            f"Left guild. Total guilds: {total}",
            embeds=[
                await embedize_guild(guild, self.kernel.bot, entitlements, owner),
                embedize_user(owner),
            ],
        )

    async def log(
        self,
        guild: hikari.SnowflakeishOr[hikari.Guild],
        message: Message,
        reason: Message | None = None,
        referenced_message: hikari.PartialMessage | None = None,
    ) -> None:
        logger.debug(
            f"log guild={guild} message={message} reason={reason} "
            f"referenced_message={referenced_message}"
        )
        now = utc_datetime()
        if isinstance(guild, hikari.Guild):
            await self._log_queue.put(
                LogJob(guild, message, reason, referenced_message, now)
            )
        else:
            new_guild = self.kernel.bot.cache.get_guild(guild)
            if new_guild is None:
                logger.debug(f"ignored delete for unknown guild: {guild}")
                return
            await self._log_queue.put(
                LogJob(new_guild, message, reason, referenced_message, now)
            )

    async def logging_task(self) -> None:
        guilds: dict[int, list[LogJob]] = defaultdict(list)
        me = self.kernel.bot.cache.get_me()
        assert me is not None, "sad"
        while True:
            await asyncio.sleep(1)
            while not self._log_queue.empty():
                log = self._log_queue.get_nowait()
                guilds[log.guild.id].append(log)

            futures = []
            for guild_id, logs in guilds.items():
                guild = logs[0].guild

                referenced_message: hikari.PartialMessage | None = None
                formatted_logs, length = [], 0
                for log_index, log in enumerate(logs):
                    formatted_log = format_log(self.kernel, log)
                    if length + len(formatted_log) > 2000:
                        break
                    length += len(formatted_log)
                    if (
                        referenced_message is None
                        and log.referenced_message is not None
                    ):
                        referenced_message = log.referenced_message
                    formatted_logs.append(formatted_log)

                guilds[guild_id] = logs[log_index + 1 :]
                message = "".join(formatted_logs)

                config = await get_config(self.kernel.database, guild_id)
                entitlements = await get_entitlements(self.kernel.database, guild_id)
                channel_id = FALLBACK_LOGS

                can_send_embed = False
                if config["logging_enabled"] and config["logging_channel"] != "0":
                    my = guild.get_my_member()
                    if my is not None and my.communication_disabled_until() is None:
                        channel = guild.get_channel(int(config["logging_channel"]))
                        if channel is not None and isinstance(
                            channel, hikari.TextableGuildChannel
                        ):
                            perms = permissions_for(my, channel)
                            if perms & hikari.Permissions.ADMINISTRATOR:
                                channel_id = channel.id
                                can_send_embed = True
                            elif perms & REQUIRED_TO_SEND == REQUIRED_TO_SEND:
                                channel_id = channel.id
                                if perms & hikari.Permissions.EMBED_LINKS:
                                    can_send_embed = True

                    else:
                        if my is None:
                            logger.info(
                                f"cant send log in {guild_id}, cant find myself"
                            )
                        elif my.communication_disabled_until():
                            logger.info(f"cant send log in {guild_id}, I am in timeout")

                if channel_id == FALLBACK_LOGS:
                    can_send_embed = True

                embeds = []
                if can_send_embed:
                    if referenced_message is not None:
                        embeds.append(
                            hikari.Embed(
                                description=referenced_message.content, color=0xF43F5E
                            )
                            .set_author(
                                name=self.kernel.translate(
                                    guild.preferred_locale, "log_embed_deleted"
                                )
                            )
                            .add_field(
                                name=self.kernel.translate(
                                    guild.preferred_locale, "log_embed_channel"
                                ),
                                value=(
                                    f"<#{referenced_message.channel_id}> "
                                    f"({referenced_message.channel_id})"
                                ),
                            )
                        )
                        if referenced_message.author:
                            embeds[0].set_footer(
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
                            embeds[0].set_image(sticker.image_url)
                            embeds[0].add_field(
                                name=self.kernel.translate(
                                    guild.preferred_locale, "log_embed_sticker"
                                ),
                                value=f"{sticker.name} ({sticker.id})",
                            )

                    if channel_id == FALLBACK_LOGS:
                        if not embeds:
                            embeds.append(hikari.Embed(color=0x2F3136))
                        embeds[0].add_field("Guild", f"{guild.name} ({guild.id})")

                    if (
                        entitlements["plan"] == 0
                        and random.random() <= 0.05
                        and not await self.kernel.database.exists(
                            (f"guild:{guild_id}:logging:voting-reminder",)
                        )
                    ):
                        integrations = [
                            (
                                "Top.gg",
                                f"https://top.gg/bot/{me.id}/vote?guild=",
                            ),
                            (
                                "Discordlist.gg",
                                f"https://discordlist.gg/bot/{me.id}/vote?ref=",
                            ),
                        ]
                        embeds.append(
                            hikari.Embed(
                                title=self.kernel.translate(
                                    guild.preferred_locale, "log_vote_title"
                                ),
                                description=(
                                    self.kernel.translate(
                                        guild.preferred_locale, "log_vote_description"
                                    )
                                    + "\n\n"
                                    + "\n".join(
                                        "[`"
                                        + self.kernel.translate(
                                            guild.preferred_locale,
                                            "log_vote_integration",
                                            name=name,
                                        )
                                        + f"`]({url}{guild_id})"
                                        for name, url in integrations
                                    )
                                ),
                                color=0x6366F1,
                            ).set_footer(
                                text=self.kernel.translate(
                                    guild.preferred_locale, "log_vote_footer"
                                )
                            )
                        )
                        await self.kernel.database.set(
                            f"guild:{guild_id}:logging:voting-reminder",
                            "1",
                            ex=VOTING_REMINDER_COOLDOWN,
                        )

                futures.append(
                    self.kernel.bot.rest.create_message(
                        channel_id,
                        message,
                        embeds=embeds if embeds else hikari.UNDEFINED,
                    )
                )

            for guild_id in tuple(guilds.keys()):
                if not guilds[guild_id]:
                    del guilds[guild_id]

            await asyncio.gather(*futures)


def format_log(kernel: KernelType, log: LogJob) -> str:
    time_string = log.created_at.strftime("%H:%M:%S")
    locale = log.guild.preferred_locale
    reason = ""
    if log.reason:
        reason = f"` Reason ` {log.reason.translate(kernel, locale)}\n"
    return f"`{time_string}` {log.message.translate(kernel, locale)}\n{reason}"


class LogJob(typing.NamedTuple):
    guild: hikari.Guild
    message: Message
    reason: Message | None
    referenced_message: hikari.PartialMessage | None
    created_at: datetime
