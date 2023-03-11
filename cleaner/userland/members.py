import asyncio
import logging
import time

import hikari

from ._types import KernelType
from .helpers.permissions import is_moderator
from .helpers.settings import get_config, get_entitlements
from .helpers.task import complain_if_none, safe_background_call, safe_call

logger = logging.getLogger(__name__)


class MembersService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["members:timer"] = self.on_timer
        self.kernel.bindings["members:guild:available"] = self.guild_available
        self.kernel.bindings["members:guild:delete"] = self.guild_delete
        self.kernel.bindings["members:member:create"] = self.member_create
        self.kernel.bindings["members:member:delete"] = self.member_delete

        self.kernel.longterm.setdefault("member_counts", {})
        self.kernel.longterm.setdefault("fetched_member_guilds", set())
        self.fetch_members_lock = asyncio.Lock()

        # time for some sanity checks of the member_counts dict
        member_counts = self.kernel.longterm["member_counts"]
        guilds = self.kernel.bot.cache.get_guilds_view()
        for guild in sorted(guilds.values(), key=lambda guild: guild.member_count or 0):
            if guild.id not in self.kernel.longterm["fetched_member_guilds"]:
                self.kernel.longterm["fetched_member_guilds"].add(guild.id)
                asyncio.ensure_future(safe_call(self.request_guild_members(guild)))

            if guild.member_count is None:
                continue

            if guild.id not in member_counts:
                member_counts[guild.id] = guild.member_count

        for guild_id in tuple(member_counts):
            if guild_id not in guilds:
                del member_counts[guild_id]

    async def guild_available(self, guild: hikari.GatewayGuild) -> None:
        if guild.member_count is not None:
            self.kernel.longterm["member_counts"][guild.id] = guild.member_count
        if guild.id not in self.kernel.longterm["fetched_member_guilds"]:
            self.kernel.longterm["fetched_member_guilds"].add(guild.id)
            safe_background_call(self.request_guild_members(guild))

    async def guild_delete(self, guild_id: int) -> None:
        if guild_id in self.kernel.longterm["member_counts"]:
            del self.kernel.longterm["member_counts"][guild_id]

    async def member_create(self, guild_id: int) -> None:
        if guild_id in self.kernel.longterm["member_counts"]:
            self.kernel.longterm["member_counts"][guild_id] += 1

    async def member_delete(self, guild_id: int) -> None:
        if guild_id in self.kernel.longterm["member_counts"]:
            self.kernel.longterm["member_counts"][guild_id] -= 1

    async def request_guild_members(self, guild: hikari.GatewayGuild) -> None:
        member_count = guild.member_count or 1000
        delay = 0 if member_count < 1000 else 5 + member_count // 10_000
        async with self.fetch_members_lock:
            logger.debug(
                f"requesting guild members for {guild.id} {member_count=} {delay=}"
            )
            await self.kernel.bot.request_guild_members(guild)
            await asyncio.sleep(delay)

    async def on_timer(self) -> None:
        # might take a bit, so make a copy
        guilds = tuple(self.kernel.bot.cache.get_guilds_view().keys())
        total_start = time.monotonic()

        for guild_id in guilds:
            guild = self.kernel.bot.cache.get_guild(guild_id)
            if (
                guild is None
                or guild_id not in self.kernel.longterm["fetched_member_guilds"]
            ):
                continue  # :shrug:

            start = time.monotonic()
            await self.check_guild(guild)

            # this very cpu intensive, so give the rest some time off
            delta = time.monotonic() - start
            logger.debug(f"periodic check for guild {guild_id} took {delta:.3f}s")
            await asyncio.sleep(delta)

        delta = time.monotonic() - total_start
        logger.debug(f"full periodic check for {len(guilds)} took {delta:.3f}s")

    async def check_guild(self, guild: hikari.GatewayGuild) -> None:
        config = await get_config(self.kernel, guild.id)
        entitlements = await get_entitlements(self.kernel, guild.id)

        bansync_ban = complain_if_none(
            self.kernel.bindings.get("bansync:ban"), "bansync:ban"
        )
        analyze_name = complain_if_none(
            self.kernel.bindings.get("name:create"), "name:create"
        )
        dehoist_member = complain_if_none(
            self.kernel.bindings.get("dehoist:create"), "dehoist:create"
        )

        banlists: list[set[int]] = []
        all_banlists: set[int] = set()

        if bansync_ban is not None:
            for list_id in config["bansync_subscribed"]:
                in_the_list = await self.kernel.database.smembers(
                    f"bansync:banlist:{list_id}:users"
                )
                banlist = set(map(int, in_the_list))
                banlists.append(banlist)
                all_banlists.update(banlist)

        if (
            not all_banlists
            and (
                not analyze_name
                or (
                    not config["name_discord_enabled"]
                    and not config["name_advanced_enabled"]
                )
            )
            and (not dehoist_member or not config["name_dehoisting_enabled"])
        ):
            logger.debug(
                f"skipped period member check for guild {guild.id} - "
                f"all relevant components disabled"
            )
            return  # short circuit to save some resources

        members = guild.get_members()
        member_ids = tuple(members.keys())

        without_sleep = 0
        for member_id in member_ids:
            member = members.get(member_id)
            if member is None:
                continue  # my man left real quick
            elif is_moderator(member, guild, config):
                continue

            if bansync_ban and member_id in all_banlists:
                # aight this guy should be banned
                # figure out the exact ban
                for index, banlist in enumerate(banlists):
                    if member_id in banlist:
                        break
                else:
                    index = 0  # shrug

                list_id = config["bansync_subscribed"][index]
                await safe_call(bansync_ban(member, config, list_id))
                without_sleep = 0

            elif (
                analyze_name
                and (config["name_discord_enabled"] or config["name_advanced_enabled"])
                and await safe_call(analyze_name(member, config, entitlements))
            ):
                without_sleep = 0

            elif (
                dehoist_member
                and config["name_dehoisting_enabled"]
                and await safe_call(dehoist_member(member))
            ):
                without_sleep = 0

            else:
                without_sleep += 1
                if without_sleep and without_sleep % 1_000 == 0:
                    await asyncio.sleep(0.1)
