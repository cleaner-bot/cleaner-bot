"""
Consumer for basic things such as most events.
"""

import asyncio
import logging
import typing

import hikari

from .._types import KernelType
from ..helpers.binding import complain_if_none, safe_call
from ..helpers.permissions import is_moderator
from ..helpers.settings import get_config, get_entitlements

logger = logging.getLogger(__name__)


class BasicConsumerService:
    events: tuple[
        tuple[
            typing.Type[hikari.Event],
            typing.Callable[
                [typing.Any], typing.Coroutine[typing.Any, typing.Any, None]
            ],
        ],
        ...,
    ]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.events = (
            (hikari.GuildMessageCreateEvent, self.on_message_create),
            (hikari.GuildMessageUpdateEvent, self.on_message_update),
            (hikari.MemberCreateEvent, self.on_member_create),
            (hikari.MemberUpdateEvent, self.on_member_update),
            (hikari.MemberDeleteEvent, self.on_member_delete),
            (hikari.BanCreateEvent, self.on_ban_create),
            (hikari.BanDeleteEvent, self.on_ban_delete),
            (hikari.GuildAvailableEvent, self.on_guild_available),
            (hikari.GuildJoinEvent, self.on_guild_join),
            (hikari.GuildLeaveEvent, self.on_guild_leave),
        )
        for type, callback in self.events:
            self.kernel.bot.subscribe(type, callback)
        self.tasks = [asyncio.create_task(self.timer_task(), name="consumer.timer")]

    def on_unload(self) -> None:
        for type, callback in self.events:
            self.kernel.bot.unsubscribe(type, callback)
        for task in self.tasks:
            task.cancel()

    async def on_message_create(self, event: hikari.GuildMessageCreateEvent) -> None:
        config = await get_config(self.kernel, event.guild_id)
        entitlements = await get_entitlements(self.kernel, event.guild_id)
        guild = event.get_guild()
        is_mod = is_moderator(event.member, guild, config)

        if event.is_bot:
            # 0. Special interactions antispam
            if event.message.interaction:
                pass  # todo: interaction antispam

        else:
            # 1. Analytics (traffic metadata)
            if radar := complain_if_none(
                self.kernel.bindings.get("radar:message"), "radar:message"
            ):
                await safe_call(radar(event.message, config, entitlements))

            if not is_mod:
                # 2. Slowmode
                if (
                    config["slowmode_enabled"]
                    and entitlements["plan"] >= entitlements["slowmode"]
                ):
                    if slowmode := complain_if_none(
                        self.kernel.bindings.get("slowmode"), "slowmode"
                    ):
                        await safe_call(slowmode(event.message, config, entitlements))

                # 3. Anti Spam
                if entitlements["plan"] >= entitlements["antispam"]:
                    if antispam := complain_if_none(
                        self.kernel.bindings.get("antispam"), "antispam"
                    ):
                        if await safe_call(
                            antispam(event.message, config, entitlements)
                        ):
                            return

                # 4. Auto Moderator
                if entitlements["plan"] >= entitlements["automod"]:
                    if automod := complain_if_none(
                        self.kernel.bindings.get("automod"), "automod"
                    ):
                        if await safe_call(
                            automod(event.message, config, entitlements)
                        ):
                            return

                # 5. Link Filter
                if (
                    entitlements["plan"] >= entitlements["linkfilter"]
                    and config["linkfilter_enabled"]
                ):
                    if linkfilter := complain_if_none(
                        self.kernel.bindings.get("linkfilter"), "linkfilter"
                    ):
                        if await safe_call(
                            linkfilter(event.message, config, entitlements)
                        ):
                            return

                # 6. Dehoist
                if (
                    event.member is not None
                    and event.message.type == hikari.MessageType.DEFAULT
                    and config["name_dehoisting_enabled"]
                ):
                    if dehoist := complain_if_none(
                        self.kernel.bindings.get("dehoist:create"), "dehoist:create"
                    ):
                        if await safe_call(dehoist(event.member)):
                            return

        # 6. Dev commands
        if self.kernel.is_developer(event.author_id):
            if dev := complain_if_none(self.kernel.bindings.get("dev"), "dev"):
                await safe_call(dev(event.message, config, entitlements))

    async def on_message_update(self, event: hikari.GuildMessageUpdateEvent) -> None:
        if event.is_bot or not event.member:
            return
        config = await get_config(self.kernel, event.guild_id)

        guild = event.get_guild()
        if is_moderator(event.member, guild, config):
            return

        entitlements = await get_entitlements(self.kernel, event.guild_id)

        # 1. Auto Moderator
        if entitlements["plan"] >= entitlements["automod"]:
            if automod := complain_if_none(
                self.kernel.bindings.get("automod"), "automod"
            ):
                await safe_call(automod(event.message, config, entitlements))

        # 2. Link Filter
        if (
            entitlements["plan"] >= entitlements["linkfilter"]
            and config["linkfilter_enabled"]
        ):
            if linkfilter := complain_if_none(
                self.kernel.bindings.get("linkfilter"), "linkfilter"
            ):
                if await safe_call(linkfilter(event.message, config, entitlements)):
                    return

    async def on_member_create(self, event: hikari.MemberCreateEvent) -> None:
        config = await get_config(self.kernel, event.guild_id)
        entitlements = await get_entitlements(self.kernel, event.guild_id)

        # 0. Remove from deduplicator
        if http_member_create := complain_if_none(
            self.kernel.bindings.get("http:member:create"),
            "http:member:create",
        ):
            await safe_call(http_member_create(event.member))

        # 1. Analytics (total user count)
        if members_member_create := complain_if_none(
            self.kernel.bindings.get("members:member:create"),
            "members:member:create",
        ):
            await safe_call(members_member_create(event.guild_id))

        # 2. User in banlist
        if bansync := complain_if_none(
            self.kernel.bindings.get("bansync:member:create"), "bansync:member:create"
        ):
            if await safe_call(bansync(event.member, config, entitlements)):
                return

        if not event.user.is_bot:
            # 3. User suspended check
            if suspension := complain_if_none(
                self.kernel.bindings.get("suspension:user"), "suspension:user"
            ):
                if await safe_call(suspension(event.member, config, entitlements)):
                    return

            # 4. Join Guard
            if (
                config["joinguard_captcha"]
                and entitlements["plan"] >= entitlements["joinguard"]
            ):
                if joinguard := complain_if_none(
                    self.kernel.bindings.get("joinguard"), "joinguard"
                ):
                    if await safe_call(joinguard(event.member, config, entitlements)):
                        return

            # 5. Anti-Raid
            if (
                config["antiraid_enabled"]
                and entitlements["plan"] >= entitlements["antiraid"]
            ):
                if antiraid := complain_if_none(
                    self.kernel.bindings.get("antiraid"), "antiraid"
                ):
                    if await safe_call(antiraid(event.member, config, entitlements)):
                        return

            # 6. Name Checker
            if config["name_discord_enabled"] or config["name_advanced_enabled"]:
                if name_create := complain_if_none(
                    self.kernel.bindings.get("name:create"),
                    "name:create",
                ):
                    if await safe_call(name_create(event.member, config, entitlements)):
                        return

            # 7. Timelimit (add to list)
            if (
                config["verification_timelimit_enabled"]
                and entitlements["plan"] >= entitlements["verification_timelimit"]
            ):
                if timelimit_create := complain_if_none(
                    self.kernel.bindings.get("timelimit:create"),
                    "timelimit:create",
                ):
                    await safe_call(timelimit_create(event.member))

            # 8. Dehoist
            if config["name_dehoisting_enabled"]:
                if dehoist := complain_if_none(
                    self.kernel.bindings.get("dehoist:create"), "dehoist:create"
                ):
                    await safe_call(dehoist(event.member), True)

        # 9. Logging
        if (
            config["logging_enabled"]
            and config["logging_option_join"]
            and entitlements["plan"] >= entitlements["logging"]
        ):
            if log_member_create := complain_if_none(
                self.kernel.bindings.get("log:member:create"), "log:member:create"
            ):
                await safe_call(log_member_create(event.member))

    async def on_member_update(self, event: hikari.MemberUpdateEvent) -> None:
        config = await get_config(self.kernel, event.guild_id)
        entitlements = await get_entitlements(self.kernel, event.guild_id)

        is_mod = is_moderator(event.member, event.get_guild(), config)
        if is_mod:
            return

        # 2. Name checker
        if config["name_discord_enabled"] or config["name_advanced_enabled"]:
            if name_update := complain_if_none(
                self.kernel.bindings.get("name:update"), "name:update"
            ):
                if await safe_call(name_update(event, config, entitlements)):
                    return

        # 3. Dehoisting
        # if entitlements["plan"] >= entitlements["dehoist"]:
        if config["name_dehoisting_enabled"]:
            if dehoist := complain_if_none(
                self.kernel.bindings.get("dehoist:update"), "dehoist:update"
            ):
                if await safe_call(dehoist(event)):
                    return

    async def on_member_delete(self, event: hikari.MemberDeleteEvent) -> None:
        config = await get_config(self.kernel, event.guild_id)
        entitlements = await get_entitlements(self.kernel, event.guild_id)

        # 1. Timelimit (remove from list)
        if (
            not event.user.is_bot
            and config["verification_timelimit_enabled"]
            and entitlements["plan"] >= entitlements["verification_timelimit"]
        ):
            if timelimit_delete := complain_if_none(
                self.kernel.bindings.get("timelimit:delete"),
                "timelimit:delete",
            ):
                await safe_call(timelimit_delete(event.guild_id, event.user_id))

        # 2. Logging
        if (
            config["logging_enabled"]
            and config["logging_option_leave"]
            and entitlements["plan"] >= entitlements["logging"]
        ):
            if log_member_delete := complain_if_none(
                self.kernel.bindings.get("log:member:delete"), "log:member:delete"
            ):
                await safe_call(log_member_delete(event.guild_id, event.user_id))

        # 3. Analytics (total user count)
        if members_member_delete := complain_if_none(
            self.kernel.bindings.get("members:member:delete"),
            "members:member:delete",
        ):
            await safe_call(members_member_delete(event.guild_id))

    async def on_ban_create(self, event: hikari.BanCreateEvent) -> None:
        # 1. Ban Synchronization
        if bansync := complain_if_none(
            self.kernel.bindings.get("bansync:ban:create"), "bansync:ban:create"
        ):
            await safe_call(bansync(event))

    async def on_ban_delete(self, event: hikari.BanDeleteEvent) -> None:
        # 1. Ban Synchronization
        if bansync := complain_if_none(
            self.kernel.bindings.get("bansync:ban:delete"), "bansync:ban:delete"
        ):
            await safe_call(bansync(event))

    async def on_guild_available(self, event: hikari.GuildAvailableEvent) -> None:
        # 1. Analytics (total user count)
        if members_guild_available := complain_if_none(
            self.kernel.bindings.get("members:guild:available"),
            "members:guild:available",
        ):
            await safe_call(members_guild_available(event.guild))

    async def on_guild_join(self, event: hikari.GuildJoinEvent) -> None:
        entitlements = await get_entitlements(self.kernel, event.guild_id)
        # 1. Guild suspended check
        is_suspended = False
        if suspension := complain_if_none(
            self.kernel.bindings.get("suspension:guild"), "suspension:guild"
        ):
            if await safe_call(suspension(event.guild, entitlements)):
                is_suspended = True

        if not is_suspended:
            # 2. Dashboard synchronization
            pass

        # 3. Analytics (total user count)
        if members_guild_available := complain_if_none(
            self.kernel.bindings.get("members:guild:available"),
            "members:guild:available",
        ):
            await safe_call(members_guild_available(event.guild))

        # 4. Dev logs
        if log_guild_join := complain_if_none(
            self.kernel.bindings.get("log:guild:join"), "log:guild:join"
        ):
            await safe_call(log_guild_join(event.guild, entitlements))

    async def on_guild_leave(self, event: hikari.GuildLeaveEvent) -> None:
        entitlements = await get_entitlements(self.kernel, event.guild_id)
        # 1. Dashboard synchronization
        # 2. Analytics (total user count)
        if members_guild_delete := complain_if_none(
            self.kernel.bindings.get("members:guild:delete"),
            "members:guild:delete",
        ):
            await safe_call(members_guild_delete(event.guild_id))

        # 3. Dev logs
        if log_guild_leave := complain_if_none(
            self.kernel.bindings.get("log:guild:leave"), "log:guild:leave"
        ):
            await safe_call(
                log_guild_leave(event.guild_id, event.old_guild, entitlements)
            )

    async def timer_task(self) -> None:
        sequence = 0
        while True:
            # 1. Slowmode
            if slowmode_timer := complain_if_none(
                self.kernel.bindings.get("slowmode:timer"), "slowmode:timer"
            ):
                await safe_call(slowmode_timer(), True)

            # 2. Verification
            if timelimit_timer := complain_if_none(
                self.kernel.bindings.get("timelimit:timer"),
                "timelimit:timer",
            ):
                await safe_call(timelimit_timer(), True)

            # 3. Raid detection ("radar")
            if radar_timer := complain_if_none(
                self.kernel.bindings.get("radar:timer"), "radar:timer"
            ):
                await safe_call(radar_timer(), True)

            # 4. Publish stats to radar and statistics
            if sequence % (5 * 6) == 0:  # only run every 5mins
                if statistics_save := complain_if_none(
                    self.kernel.bindings.get("statistics:save"), "statistics:save"
                ):
                    await safe_call(statistics_save(), True)

            # 5. Re-check members in servers etc and save data
            if (
                sequence % (15 * 6) == 5 * 6
            ):  # only run every 15mins, starting after 5mins
                loop = asyncio.get_event_loop()
                if data_save := complain_if_none(
                    self.kernel.bindings.get("data:save"), "data:save"
                ):
                    await safe_call(loop.run_in_executor(None, data_save, None), True)

                if members_timer := complain_if_none(
                    self.kernel.bindings.get("members:timer"), "data:save"
                ):
                    await safe_call(members_timer(), True)

            # 6. Publish stats to integrations
            if sequence % (30 * 6) == 5 * 6:  # only run every 30mins
                if integration_timer := complain_if_none(
                    self.kernel.bindings.get("integration:timer"), "integration:timer"
                ):
                    await safe_call(integration_timer(), True)

            # sleep
            sequence += 1
            await asyncio.sleep(10)
