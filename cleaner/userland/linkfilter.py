from __future__ import annotations

import logging
import typing
from base64 import urlsafe_b64encode
from hashlib import sha256

import hikari
from expirepy import ExpiringSet

from ._types import (
    ConfigType,
    EntitlementsType,
    InteractionResponse,
    KernelType,
    LinkFilteredEvent,
)
from .helpers.binding import complain_if_none, safe_call
from .helpers.localization import Message
from .helpers.permissions import permissions_for
from .helpers.url import get_urls, has_url

logger = logging.getLogger(__name__)
REQUIRED_TO_SEND = (
    hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.EMBED_LINKS
)
URL_EXPIRE = 60 * 60 * 24 * 3


class LinkFilterService:
    deduplicator: ExpiringSet[str]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["linkfilter"] = self.analyze_message

        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "lf-whitelist-u": self.btn_whitelist_url,
            "lf-whitelist-d": self.btn_whitelist_domain,
            "lf-blacklist-u": self.btn_blacklist_url,
            "lf-blacklist-d": self.btn_blacklist_domain,
            "lf-dismiss": self.btn_dismiss,
        }
        self.kernel.interactions["components"].update(components)

        self.deduplicator = ExpiringSet(300)

    async def analyze_message(
        self,
        message: hikari.PartialMessage,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> bool:
        if not message.content:
            return False

        assert message.member, "impossible"
        if not has_url(message.content):
            return False

        whitelist = [
            x.decode()
            for x in await self.kernel.database.lrange(
                f"guild:{message.guild_id}:linkfilter:whitelist", 0, -1
            )
        ]
        blacklist = [
            x.decode()
            for x in await self.kernel.database.lrange(
                f"guild:{message.guild_id}:linkfilter:blacklist", 0, -1
            )
        ]
        urls = []
        for url in get_urls(message.content):
            # remove scheme and trailing /
            url = "/".join(url.split("/")[2:]).strip("/")
            if url.startswith("www."):
                url = url[4:]

            urls.append(url)

        blacklisted = False
        last_url: str = ""
        for url in urls:
            if self.matches_url(url, whitelist):
                pass
            elif self.matches_url(url, blacklist):
                blacklisted = True
                last_url = url
                break
            else:
                last_url = url

        if not last_url:
            return False

        logger.debug(
            f"author={message.member.user} ({message.member.id}) "
            f"url={last_url} in {message.guild_id} ({blacklisted})"
        )

        reason = Message(
            "linkfilter_reason_blacklisted"
            if blacklisted
            else "linkfilter_reason_unknown",
            {"url": last_url},
        )
        is_bad = blacklisted or config["linkfilter_blockunknown"]

        if is_bad:
            if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
                info: LinkFilteredEvent = {
                    "name": "linkfilter",
                    "guild_id": message.member.guild_id,
                    "url": last_url,
                }
                await safe_call(track(info), True)

            if delete := complain_if_none(
                self.kernel.bindings.get("http:delete"), "http:delete"
            ):
                await safe_call(
                    delete(
                        message.id,
                        message.channel_id,
                        message.member.user,
                        True,
                        reason,
                        message,
                    ),
                    True,
                )

            if challenge := complain_if_none(
                self.kernel.bindings.get("http:challenge"), "http:challenge"
            ):
                await safe_call(
                    challenge(
                        message.member,
                        config,
                        True,
                        reason,
                        0,
                    ),
                    True,
                )

            if announcement := complain_if_none(
                self.kernel.bindings.get("http:announcement"),
                "http:announcement",
            ):
                announcement_message = Message(
                    "linkfilter_blacklisted" if blacklisted else "linkfilter_unknown",
                    {"user": message.member.id},
                )

                assert isinstance(message.app, hikari.CacheAware)
                channel = message.app.cache.get_guild_channel(message.channel_id)
                if channel is not None and isinstance(
                    channel, hikari.TextableGuildChannel
                ):
                    await safe_call(
                        announcement(channel, announcement_message, 20), True
                    )

        key = f"{message.guild_id}-{last_url}"
        if key not in self.deduplicator:
            self.deduplicator.add(key)
            await self.send_link_check(message, last_url, config, is_bad)

        return is_bad

    def matches_url(self, url: str, collection: list[str]) -> bool:
        for match in collection:
            any_start = match.startswith("*")
            any_end = match.endswith("*")

            if any_start and any_end:
                if match[1:-1] in url:
                    return True

            elif any_start:
                if url.endswith(match[1:]):
                    return True

            elif any_end:
                if url.startswith(match[:-1]):
                    return True

            elif url == match:
                return True

        return False

    async def send_link_check(
        self,
        message: hikari.PartialMessage,
        url: str,
        config: ConfigType,
        is_deleted: bool,
    ) -> None:
        assert message.guild_id, "impossible"
        assert message.member, "impossible"

        if (guild := self.kernel.bot.cache.get_guild(message.guild_id)) is None:
            return
        elif (me := guild.get_my_member()) is None:
            return
        elif config["linkfilter_channel"] == "0":
            return
        elif (
            channel := guild.get_channel(int(config["linkfilter_channel"]))
        ) is None or not isinstance(channel, hikari.TextableGuildChannel):
            await self._error(
                message.guild_id, Message("linkfilter_error_channel_notfound")
            )
            return

        perms = permissions_for(me, channel)
        if perms & hikari.Permissions.ADMINISTRATOR:
            pass
        elif perms & REQUIRED_TO_SEND != REQUIRED_TO_SEND:
            await self._error(
                message.guild_id,
                Message(
                    "linkfilter_error_channel_permissions",
                    {"channel": config["linkfilter_channel"]},
                ),
            )
            return

        url_id = urlsafe_b64encode(sha256(url.encode()).digest()).decode()
        domain = url.split("/")[0]
        await self.kernel.database.set(
            f"linkfilter:url-resolver:{url_id}", url, ex=URL_EXPIRE
        )

        i18n = (self.kernel, guild.preferred_locale)
        embed = hikari.Embed(
            title=Message("linkfilter_embed_title").translate(*i18n),
            description=Message(
                "linkfilter_embed_description", {"url": url, "domain": domain}
            ).translate(*i18n),
            color=0x2F3136,
        ).set_footer(text=str(message.member), icon=message.member.make_avatar_url())

        components = [self.kernel.bot.rest.build_action_row() for _ in range(3)]
        (
            components[0]
            .add_button(hikari.ButtonStyle.SUCCESS, f"lf-whitelist-u/{url_id}")
            .set_label(Message("linkfilter_button_whitelist_url").translate(*i18n))
            .add_to_container()
        )
        (
            components[0]
            .add_button(hikari.ButtonStyle.SUCCESS, f"lf-whitelist-d/{url_id}")
            .set_label(Message("linkfilter_button_whitelist_domain").translate(*i18n))
            .add_to_container()
        )
        (
            components[1]
            .add_button(hikari.ButtonStyle.DANGER, f"lf-blacklist-u/{url_id}")
            .set_label(Message("linkfilter_button_blacklist_url").translate(*i18n))
            .add_to_container()
        )
        (
            components[1]
            .add_button(hikari.ButtonStyle.DANGER, f"lf-blacklist-d/{url_id}")
            .set_label(Message("linkfilter_button_blacklist_domain").translate(*i18n))
            .add_to_container()
        )

        if not is_deleted:
            (
                components[2]
                .add_button(hikari.ButtonStyle.LINK, message.make_link(guild))
                .set_label(Message("linkfilter_button_jump").translate(*i18n))
                .add_to_container()
            )

        (
            components[2]
            .add_button(hikari.ButtonStyle.SECONDARY, "lf-dismiss")
            .set_label(Message("linkfilter_button_dismiss").translate(*i18n))
            .add_to_container()
        )

        await channel.send(embed=embed, components=components)

    async def _error(self, guild_id: int, message: Message) -> None:
        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            await safe_call(log(guild_id, message, None, None), True)

    async def btn_whitelist_url(
        self, interaction: hikari.ComponentInteraction, url_id: str
    ) -> InteractionResponse:
        return await self.handle_button(interaction, url_id, "whitelist", False)

    async def btn_whitelist_domain(
        self, interaction: hikari.ComponentInteraction, url_id: str
    ) -> InteractionResponse:
        return await self.handle_button(interaction, url_id, "whitelist", True)

    async def btn_blacklist_url(
        self, interaction: hikari.ComponentInteraction, url_id: str
    ) -> InteractionResponse:
        return await self.handle_button(interaction, url_id, "blacklist", False)

    async def btn_blacklist_domain(
        self, interaction: hikari.ComponentInteraction, url_id: str
    ) -> InteractionResponse:
        return await self.handle_button(interaction, url_id, "blacklist", True)

    async def handle_button(
        self,
        interaction: hikari.ComponentInteraction,
        url_id: str,
        category: str,
        domain: bool,
    ) -> InteractionResponse:
        raw_url = await self.kernel.database.get(f"linkfilter:url-resolver:{url_id}")
        if raw_url is None:
            await interaction.edit_message(
                interaction.message,
                content=Message("linkfilter_action_expired").translate(
                    self.kernel, interaction.locale
                ),
                components=[],
            )
            return {
                "content": Message("linkfilter_action_expired").translate(
                    self.kernel, interaction.locale
                )
            }

        url = raw_url.decode()
        if domain:
            the_domain = url[0].split("/")[0]
            url = f"{the_domain}*"

        await self.kernel.database.rpush(
            f"guild:{interaction.guild_id}:linkfilter:{category}", (url,)
        )

        action = f"linkfilter_action_{category}_" + ("domain" if domain else "url")
        await interaction.edit_message(
            interaction.message,
            content=Message(action).translate(self.kernel, interaction.locale),
            components=[],
        )
        return {"content": Message(action).translate(self.kernel, interaction.locale)}

    async def btn_dismiss(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        await interaction.edit_message(
            interaction.message,
            content=Message("linkfilter_action_dismiss").translate(
                self.kernel, interaction.locale
            ),
            components=[],
        )
        return {
            "content": Message("linkfilter_action_dismiss").translate(
                self.kernel, interaction.locale
            )
        }
