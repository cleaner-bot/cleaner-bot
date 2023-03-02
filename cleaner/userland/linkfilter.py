from __future__ import annotations

import hmac
import logging
import os
import typing
from urllib.parse import urlencode

import hikari
from expirepy import ExpiringSet
from httpx import URL

from ._types import (
    ConfigType,
    EntitlementsType,
    InteractionResponse,
    KernelType,
    LinkFilteredEvent,
)
from .helpers.localization import Message
from .helpers.permissions import permissions_for
from .helpers.task import complain_if_none, safe_background_call
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
            "lf-btn": self.handle_button,
            "lf-dismiss": self.btn_dismiss,
            "lf-undo": self.btn_undo,
        }
        modals = {
            "lf-modal": self.handle_modal,
        }
        self.kernel.interactions["components"].update(components)
        self.kernel.interactions["modals"].update(modals)

        self.deduplicator = ExpiringSet(300)

    async def analyze_message(
        self,
        message: hikari.PartialMessage,
        config: ConfigType,
        entitlements: EntitlementsType,
    ) -> bool:
        assert message.guild_id
        if not message.content:
            return False

        assert message.member, "impossible"
        if not has_url(message.content):
            return False

        whitelist = [
            parse_url(x.decode())
            for x in await self.kernel.database.lrange(
                f"guild:{message.guild_id}:linkfilter:whitelist", 0, -1
            )
        ]
        blacklist = [
            parse_url(x.decode())
            for x in await self.kernel.database.lrange(
                f"guild:{message.guild_id}:linkfilter:blacklist", 0, -1
            )
        ]

        urls = list(map(URL, get_urls(message.content)))
        blacklisted = False
        last_url: URL | None = None
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
                }
                safe_background_call(track(info))

            if delete := complain_if_none(
                self.kernel.bindings.get("http:delete"), "http:delete"
            ):
                safe_background_call(
                    delete(
                        message.id,
                        message.channel_id,
                        message.member.user,
                        True,
                        reason,
                        message,
                    ),
                )

            if challenge := complain_if_none(
                self.kernel.bindings.get("http:challenge"), "http:challenge"
            ):
                safe_background_call(
                    challenge(
                        message.member,
                        config,
                        True,
                        reason,
                        0,
                    ),
                )

            if announcement := complain_if_none(
                self.kernel.bindings.get("http:announcement"),
                "http:announcement",
            ):
                announcement_message = Message(
                    "linkfilter_blacklisted" if blacklisted else "linkfilter_unknown",
                    {"user": message.member.id},
                )

                safe_background_call(
                    announcement(
                        message.guild_id, message.channel_id, announcement_message, 20
                    ),
                )

        key = f"{message.guild_id}-{last_url}"
        if key not in self.deduplicator and not blacklisted:
            self.deduplicator.add(key)
            await self.send_link_check(message, last_url, config, is_bad)

        return is_bad

    def matches_url(self, url: URL, collection: list[URL]) -> bool:
        for match in collection:
            if (
                (not match.scheme or does_match(url.scheme, match.scheme))
                and does_match(url.netloc.decode(), match.netloc.decode())
                and does_match(url.path, match.path)
                and (not match.query or does_match(str(url.params), str(match.params)))
            ):
                return True

        return False

    async def send_link_check(
        self,
        message: hikari.PartialMessage,
        url: URL,
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

        i18n = (self.kernel, guild.preferred_locale)
        embed = hikari.Embed(
            title=Message("linkfilter_embed_title").translate(*i18n),
            description=Message(
                "linkfilter_embed_description", {"url": str(url).replace("`", "")}
            ).translate(*i18n),
            color=0x2F3136,
        ).set_footer(text=str(message.member), icon=message.member.make_avatar_url())

        if config["linkfilter_linkpreview"]:
            embed.set_image(generate_webpreview(url))

        components = self._build_components(
            guild.preferred_locale, None if is_deleted else message.make_link(guild)
        )
        await channel.send(embed=embed, components=components)

    async def _error(self, guild_id: int, message: Message) -> None:
        if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
            safe_background_call(log(guild_id, message, None, None))

    async def handle_button(
        self,
        interaction: hikari.ComponentInteraction,
        category: str,
    ) -> InteractionResponse:
        description = interaction.message.embeds[0].description
        assert description
        raw_url = description.split("`")[1]
        url = URL(raw_url, scheme="*")

        component = self.kernel.bot.rest.build_modal_action_row()
        (
            component.add_text_input(
                "url",
                Message("linkfilter_modal_label_" + category).translate(
                    self.kernel, interaction.locale
                ),
            )
            .set_style(hikari.TextInputStyle.SHORT)
            .set_min_length(4)
            .set_max_length(200)
            .set_value(str(url)[:128])
            .set_placeholder(
                Message("linkfilter_modal_placeholder").translate(
                    self.kernel, interaction.locale
                )
            )
            .add_to_container()
        )

        await interaction.create_modal_response(
            Message("report_message_modal_title").translate(
                self.kernel, interaction.locale
            ),
            f"lf-modal/{category}",
            components=[component],
        )

        return {}

    async def btn_dismiss(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            content=Message("linkfilter_action_dismiss").translate(
                self.kernel, interaction.locale
            ),
            components=[],
        )
        return {}

    async def btn_undo(
        self, interaction: hikari.ComponentInteraction, category: str
    ) -> InteractionResponse:
        content = interaction.message.content
        assert content
        url = content.split("`")[1]

        await self.kernel.database.lrem(
            f"guild:{interaction.guild_id}:linkfilter:{category}", 0, url
        )

        jump_link = None
        if len(interaction.message.components[0].components) >= 2:
            link = typing.cast(
                hikari.ButtonComponent, interaction.message.components[1][0]
            )
            assert link.url
            jump_link = link.url

        assert interaction.guild_locale
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            content="",
            components=self._build_components(interaction.guild_locale, jump_link),
        )
        return {}

    def _build_components(
        self, locale: str, jump_link: str | None
    ) -> list[hikari.api.MessageActionRowBuilder]:
        components = [self.kernel.bot.rest.build_message_action_row()]
        (
            components[0]
            .add_button(hikari.ButtonStyle.SUCCESS, "lf-btn/whitelist")
            .set_label(
                Message("linkfilter_button_whitelist").translate(self.kernel, locale)
            )
            .add_to_container()
        )
        (
            components[0]
            .add_button(hikari.ButtonStyle.DANGER, "lf-btn/blacklist")
            .set_label(
                Message("linkfilter_button_blacklist").translate(self.kernel, locale)
            )
            .add_to_container()
        )

        if jump_link:
            components.append(self.kernel.bot.rest.build_message_action_row())
            (
                components[-1]
                .add_button(hikari.ButtonStyle.LINK, jump_link)
                .set_label(
                    Message("linkfilter_button_jump").translate(self.kernel, locale)
                )
                .add_to_container()
            )

        (
            components[-1]
            .add_button(hikari.ButtonStyle.SECONDARY, "lf-dismiss")
            .set_label(
                Message("linkfilter_button_dismiss").translate(self.kernel, locale)
            )
            .add_to_container()
        )

        return components

    async def handle_modal(
        self, interaction: hikari.ModalInteraction, category: str
    ) -> InteractionResponse:
        assert interaction.message

        url = interaction.components[0].components[0].value.replace("`", "")

        await self.kernel.database.rpush(
            f"guild:{interaction.guild_id}:linkfilter:{category}", (url,)
        )

        component = self.kernel.bot.rest.build_message_action_row()
        if len(interaction.message.components) >= 2:
            link = typing.cast(
                hikari.ButtonComponent, interaction.message.components[1][0]
            )
            assert link.url and link.label
            (
                component.add_button(hikari.ButtonStyle.LINK, link.url)
                .set_label(link.label)
                .add_to_container()
            )

        assert interaction.guild_locale
        (
            component.add_button(hikari.ButtonStyle.DANGER, f"lf-undo/{category}")
            .set_label(
                Message("linkfilter_button_undo").translate(
                    self.kernel, interaction.guild_locale
                )
            )
            .add_to_container()
        )

        action = f"linkfilter_action_{category}"
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            content=Message(action, {"url": url}).translate(
                self.kernel, interaction.guild_locale
            ),
            component=component,
        )
        await interaction.execute(
            Message(action, {"url": url}).translate(self.kernel, interaction.locale),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return {}


def parse_url(url: str) -> URL:
    if "://" not in url:
        url = "*://" + url

    if url.startswith("*://"):
        parsed = URL("https" + url[1:])
        return parsed.copy_with(scheme="*")
    return URL(url)


def generate_webpreview(url: URL) -> str:
    origin = "https://webpreview.cleanerbot.xyz/api?"
    raw_key = os.getenv("WEBPREVIEW_SECRET")
    assert raw_key
    key = bytes.fromhex(raw_key)
    query = {"url": url, "sig": hmac.digest(key, str(url).encode(), "sha256").hex()}
    return origin + urlencode(query)


def does_match(source: str, test: str) -> bool:
    if test == "*":
        return True

    any_start = test.startswith("*")
    any_end = test.endswith("*")

    if any_start and any_end:
        if test[1:-1] in source:
            return True

    elif any_start:
        if source.endswith(test[1:]):
            return True

    elif any_end:
        if source.startswith(test[:-1]):
            return True

    return source == test
