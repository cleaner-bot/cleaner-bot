from __future__ import annotations

import logging
import typing
from collections import defaultdict
from datetime import datetime

import hikari
from decancer_py import parse
from hikari.internal.time import utc_datetime

from ._types import ConfigType, EntitlementsType, InteractionResponse, KernelType
from .helpers.binding import complain_if_none, safe_call
from .helpers.embedize import embedize_guild
from .helpers.regex import DISCORD_INVITE
from .helpers.tokenizer import tokenize
from .helpers.url import domain_in_list, get_urls, remove_urls

logger = logging.getLogger(__name__)
RAID_TIMEOUT = 2 * 60
ACTION_THRESHOLD = 5
DOMAIN_EMOJIS = {"whitelisted": "✅", "blacklisted": "⚠️", "unknown": "❔"}
INVITE_ADMIN_CHANNEL = 1028628670501376100
PHISHING_ADMIN_CHANNEL = 963043098999533619


class RadarService:
    guilds: dict[int, GuildInfo]
    reported_messages: set[str]
    invite_cache: dict[str, hikari.Invite | typing.Literal[False]]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["radar:message"] = self.message_create
        self.kernel.bindings["radar:timer"] = self.on_timer
        self.kernel.bindings["radar:raid:submit"] = self.raid_submit
        self.kernel.bindings["radar:phishing:submit"] = self.phishing_submit
        self.kernel.bindings["radar:unsafeinvite:submit"] = self.unsafeinvite_submit

        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "x-p-ban": self.btn_phishing_ban,
            "x-p-whitelist": self.btn_phishing_whitelist,
            "x-p-dismiss": self.btn_dismiss,
            "x-d-ban": self.btn_invite_ban,
            "x-d-dismiss": self.btn_dismiss,
        }
        self.kernel.interactions["components"].update(components)

        self.reported_messages = set()
        self.invite_cache = dict()
        self.guilds = defaultdict(
            lambda: {
                "start": None,
                "last_action": None,
                "kick": 0,
                "ban": 0,
                "ongoing_announced": False,
            }
        )

    async def message_create(
        self,
        message: hikari.Message,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> None:
        pass

    async def raid_submit(
        self, member: hikari.Member, field: typing.Literal["kick", "ban"]
    ) -> None:
        guild = self.guilds[member.guild_id]
        if guild["start"] is None:
            guild["start"] = guild["last_action"] = utc_datetime()
        else:
            guild["last_action"] = utc_datetime()

        guild[field] += 1

    async def on_timer(self) -> None:
        now = utc_datetime()
        for guild_id, guild in tuple(self.guilds.items()):
            if guild["start"] is None or guild["last_action"] is None:
                del self.guilds[guild_id]
                continue

            if (now - guild["last_action"]).total_seconds() < RAID_TIMEOUT:
                if guild["kick"] + guild["ban"] >= ACTION_THRESHOLD:
                    logger.debug(f"raid ongoing guild={guild_id} info={guild}")
                    if not guild["ongoing_announced"]:
                        guild["ongoing_announced"] = True
                        if raid_ongoing := complain_if_none(
                            self.kernel.bindings.get("log:raid:ongoing"),
                            "log:raid:ongoing",
                        ):
                            await safe_call(
                                raid_ongoing(
                                    guild_id,
                                    guild["start"],
                                    guild["kick"],
                                    guild["ban"],
                                )
                            )

                continue  # raid is still ongoing

            if guild["kick"] + guild["ban"] >= ACTION_THRESHOLD:
                logger.debug(f"raid complete guild={guild_id} info={guild}")

                if raid_complete := complain_if_none(
                    self.kernel.bindings.get("log:raid:complete"), "log:raid:complete"
                ):
                    await safe_call(
                        raid_complete(
                            guild_id,
                            guild["start"],
                            guild["last_action"],
                            guild["kick"],
                            guild["ban"],
                        )
                    )

            del self.guilds[guild_id]

    async def phishing_submit(self, message: hikari.Message, rule: str) -> None:
        assert message.content, "impossible"

        domains = {
            x.split("/")[2]: self.get_domain_classification(x.split("/")[2])
            for x in get_urls(message.content)
        }

        fingerprint = " ".join(
            sorted(set(x for x in tokenize(message.content.lower()) if x.strip()))
        )
        if fingerprint in self.reported_messages:
            return
        self.reported_messages.add(fingerprint)

        fingerprint = " ".join(
            sorted(
                set(
                    x
                    for x in tokenize(remove_urls(message.content.lower()))
                    if x.strip()
                )
            )
        )

        embed = hikari.Embed(description=message.content, color=0xE74C3C)
        embed.set_author(name=f"Suspicious message | {rule}")
        embed.set_footer(
            text=f"{message.author} ({message.author.id})",
            icon=message.author.make_avatar_url(ext="webp", size=64),
        )

        if message.embeds:
            evil_embed = message.embeds[0]
            if evil_embed.title:
                embed.add_field("Title", evil_embed.title)
            if evil_embed.description:
                embed.add_field("Description", evil_embed.description)
            if evil_embed.thumbnail:
                embed.add_field("Thumbnail", evil_embed.thumbnail.url)

        embed.add_field("Channel", f"<#{message.channel_id}>")

        assert message.guild_id is not None, "impossible"
        guild = self.kernel.bot.cache.get_guild(message.guild_id)
        if guild is None:
            embed.add_field("Guild", str(message.guild_id))
        else:
            embed.add_field("Guild", f"{guild.name} ({message.guild_id})")

        row = self.kernel.bot.rest.build_action_row()
        (
            row.add_button(hikari.ButtonStyle.PRIMARY, "x-p-ban")
            .set_label("Mark as correct")
            .set_is_disabled(
                fingerprint in self.kernel.data["phishing_domain_blacklist"]
                and all(
                    x in self.kernel.data["phishing_domain_blacklist"] for x in domains
                )
            )
            .add_to_container()
        )

        embeds = [embed]
        if domains:
            url_embed = hikari.Embed(
                description="\n".join(
                    DOMAIN_EMOJIS[v] + f" {k}" for k, v in domains.items()
                ),
                color=0x2F3136,
            )
            url_embed.set_author(name="Detected domains")
            embeds.append(url_embed)

            (
                row.add_button(hikari.ButtonStyle.DANGER, "x-p-whitelist")
                .set_label("Mark as false positive")
                .set_is_disabled(all(v != "unknown" for v in domains.values()))
                .add_to_container()
            )

        (
            row.add_button(hikari.ButtonStyle.SECONDARY, "x-p-dismiss")
            .set_label("Dismiss")
            .set_emoji("❌")
            .add_to_container()
        )

        await self.kernel.bot.rest.create_message(
            PHISHING_ADMIN_CHANNEL, embeds=embeds, component=row
        )

    def get_domain_classification(self, domain: str) -> str:
        if domain_in_list(domain, self.kernel.data["phishing_domain_whitelist"]):
            return "whitelisted"
        elif domain_in_list(domain, self.kernel.data["phishing_domain_blacklist"]):
            return "blacklisted"
        return "unknown"

    async def unsafeinvite_submit(self, message: hikari.Message) -> None:
        assert message.content, "impossible"

        all_invites: list[hikari.Invite] = []
        for _, invite in DISCORD_INVITE.findall(message.content):
            if invite in self.kernel.data["discord_invite_blacklist"]:
                continue

            try:
                inv = self.invite_cache.get(invite)
                if inv is None:
                    inv = await self.kernel.bot.rest.fetch_invite(invite)
            except hikari.NotFoundError:
                self.invite_cache[invite] = inv = False

            if (
                inv
                and inv.guild is not None
                and hikari.GuildFeature.VERIFIED not in inv.guild.features
                and hikari.GuildFeature.PARTNERED not in inv.guild.features
                and (inv.approximate_member_count or 0) > 100
            ):
                all_invites.append(inv)

        if not all_invites:
            return

        embed = hikari.Embed(description=message.content, color=0xE74C3C)
        embed.set_author(name="Suspicious message")
        embed.set_footer(
            text=f"{message.author} ({message.author.id})",
            icon=message.author.make_avatar_url(ext="webp", size=64),
        )

        if message.embeds:
            evil_embed = message.embeds[0]
            if evil_embed.title:
                embed.add_field("Title", evil_embed.title)
            if evil_embed.description:
                embed.add_field("Description", evil_embed.description)
            if evil_embed.thumbnail:
                embed.add_field("Thumbnail", evil_embed.thumbnail.url)

        embed.add_field("Channel", f"<#{message.channel_id}>")

        assert message.guild_id is not None, "impossible"
        guild = self.kernel.bot.cache.get_guild(message.guild_id)
        if guild is None:
            embed.add_field("Guild", str(message.guild_id))
        else:
            embed.add_field("Guild", f"{guild.name} ({message.guild_id})")

        embeds = [embed]
        invites_blacklist = []
        row = self.kernel.bot.rest.build_action_row()

        for invite in all_invites[:5]:
            assert invite.guild is not None, "impossible"
            invite_embed = await embedize_guild(invite.guild, self.kernel.bot, None)
            invite_embed.add_field("Invite code", invite.code)
            name = parse(invite.guild.name)
            if (
                "18+" in name
                or "nudes" in name
                or name.startswith("family")
                or "sex" in name
                or "boob" in name
            ):
                if invite.code in self.kernel.data["discord_invite_blacklist"]:
                    invite_embed.add_field("Blacklisted", "✅ Already blacklisted")
                else:
                    invites_blacklist.append(invite.code)
                    invite_embed.add_field("Blacklisted", "✅ Now blacklisted")

            else:
                invite_embed.add_field("Blacklisted", "❌ Not blacklisted")
                (
                    row.add_button(hikari.ButtonStyle.DANGER, f"x-d-ban/{invite.code}")
                    .set_label(f"Ban {invite.code}")
                    .add_to_container()
                )

            embeds.append(invite_embed)

        if invites_blacklist:
            self.kernel.data["discord_invite_blacklist"].extend(invites_blacklist)
            data_changed = self.kernel.bindings.get("data:changed")
            if data_changed is not None:
                data_changed("discord_invite_blacklist")

        if row.components:
            (
                row.add_button(hikari.ButtonStyle.SECONDARY, "x-d-dismiss")
                .set_label("Dismiss")
                .add_to_container()
            )

        await self.kernel.bot.rest.create_message(
            INVITE_ADMIN_CHANNEL,
            embeds=embeds,
            components=[row] if row.components else [],
        )

    async def btn_phishing_ban(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        content = interaction.message.embeds[0].description
        assert content, "impossible"
        fingerprint = " ".join(
            sorted(set(x for x in tokenize(remove_urls(content.lower())) if x.strip()))
        )
        domains = {
            x.split("/")[2]: self.get_domain_classification(x.split("/")[2])
            for x in get_urls(content)
        }

        if fingerprint not in self.kernel.data["phishing_content"]:
            self.kernel.data["phishing_content"].append(fingerprint)
            self.kernel.data["phishing_content"].sort()

            data_changed = self.kernel.bindings.get("data:changed")
            if data_changed is not None:
                data_changed("phishing_content")

        for domain, status in domains.items():
            if status == "unknown":
                self.kernel.data["phishing_domain_blacklist"].append(domain)

        self.kernel.data["phishing_domain_blacklist"].sort()

        data_changed = self.kernel.bindings.get("data:changed")
        if data_changed is not None:
            data_changed("phishing_domain_blacklist")

        await interaction.edit_message(interaction.message, components=[])
        return {"content": ":+1:"}

    async def btn_phishing_whitelist(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        content = interaction.message.embeds[0].description
        assert content, "impossible"
        domains = {
            x.split("/")[2]: self.get_domain_classification(x.split("/")[2])
            for x in get_urls(content)
        }
        for domain, status in domains.items():
            if status == "blacklisted":
                self.kernel.data["phishing_domain_blacklist"].remove(domain)
            self.kernel.data["phishing_domain_whitelist"].append(domain)

        self.kernel.data["phishing_domain_whitelist"].sort()

        data_changed = self.kernel.bindings.get("data:changed")
        if data_changed is not None:
            data_changed("phishing_domain_whitelist")
            data_changed("phishing_domain_blacklist")

        await interaction.edit_message(interaction.message, components=[])
        return {"content": ":+1:"}

    async def btn_invite_ban(
        self, interaction: hikari.ComponentInteraction, invite: str
    ) -> InteractionResponse:
        if invite in self.kernel.data["discord_invite_blacklist"]:
            return {"content": ":-1:"}

        self.kernel.data["discord_invite_blacklist"].append(invite)
        self.kernel.data["discord_invite_blacklist"].sort()
        data_changed = self.kernel.bindings.get("data:changed")
        if data_changed is not None:
            data_changed("discord_invite_blacklist")
        return {"content": ":+1:"}

    async def btn_dismiss(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        await interaction.edit_message(interaction.message, components=[])
        return {}


class GuildInfo(typing.TypedDict):
    start: datetime | None
    last_action: datetime | None
    kick: int
    ban: int
    ongoing_announced: bool
