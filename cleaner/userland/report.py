import base64
import logging
import typing
from datetime import timedelta

import hikari
from expirepy import ExpiringDict
from hikari.internal.time import utc_datetime
from Levenshtein import ratio  # type: ignore

from ._types import ConfigType, InteractionResponse, KernelType
from .helpers.builders import components_to_builder
from .helpers.duration import duration_to_text, text_to_duration
from .helpers.escape import escape_markdown
from .helpers.localization import Message
from .helpers.permissions import is_moderator, permissions_for
from .helpers.settings import get_config, get_entitlements
from .helpers.tokenizer import tokenize
from .helpers.url import has_url, remove_urls

logger = logging.getLogger(__name__)
REPORT_MAXAGE = 60 * 60 * 24 * 3  # 3 days
REPORT_SLOWMODE_TTL = 60 * 60 * 12  # 12 hours
REPORT_SLOWMODE_LIMIT = 5
MAX_TIMEOUT_DURATION = 60 * 60 * 24 * 28
PERMS_SEND = (
    hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.EMBED_LINKS
)


class ReportService:
    message_cache: ExpiringDict[int, hikari.Message]

    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.message_cache = ExpiringDict(expires=60 * 15)

        commands = {
            "Report as phishing": self.create_phishing_report,
            "Report to server staff": self.create_message_report,
        }
        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "x-pr-ack": self.acknowldge_phishing_report,
            "x-pr-invalid": self.invalid_phishing_report,
            "x-ür-ban": self.ban_user_from_phishing_reports,
            "x-pr-unban": self.unban_user_from_phishing_reports,
            "r-a-delete": self.delete_reported_message,
            "r-a-timeout": self.timeout_reported_person,
            "r-a-kick": self.kick_reported_person,
            "r-a-ban": self.ban_reported_person,
        }
        modals: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "r-modal": self.finalize_message_report,
            "r-a-timeout": self.finalize_timeout_reported_person,
        }

        self.kernel.interactions["commands"].update(commands)
        self.kernel.interactions["components"].update(components)
        self.kernel.interactions["modals"].update(modals)

    # Phishing report

    async def create_phishing_report(
        self, interaction: hikari.CommandInteraction
    ) -> InteractionResponse:
        if interaction.guild_id is None:
            return {
                "content": Message("report_errors_guildonly").translate(
                    self.kernel, interaction.locale
                )
            }
        assert interaction.target_id is not None
        assert interaction.resolved is not None

        if (
            utc_datetime() - interaction.target_id.created_at
        ).total_seconds() > REPORT_MAXAGE:
            return {
                "content": Message("report_errors_tooold").translate(
                    self.kernel, interaction.locale
                )
            }
        elif await self.kernel.database.exists(
            (f"message:{interaction.target_id}:reported",)
        ):
            return {
                "content": Message("report_errors_already").translate(
                    self.kernel, interaction.locale
                )
            }
        elif await self.kernel.database.sismember(
            "report:phishing:banned", interaction.user.id
        ):
            return {
                "content": Message("report_phishing_errors_banned").translate(
                    self.kernel, interaction.locale
                )
            }

        message = interaction.resolved.messages.get(interaction.target_id, None)
        if message is None or message.content is None:
            return {
                "content": Message("report_errors_nomessage").translate(
                    self.kernel, interaction.locale
                )
            }
        elif message.author.is_bot:
            return {
                "content": Message("report_errors_nobot").translate(
                    self.kernel, interaction.locale
                )
            }
        elif message.author.id == interaction.user.id:
            return {
                "content": Message("report_errors_noself").translate(
                    self.kernel, interaction.locale
                )
            }
        elif not has_url(message.content):
            return {
                "content": Message("report_phishing_errors_nolink").translate(
                    self.kernel, interaction.locale
                )
            }

        content = " ".join(
            sorted(
                set(
                    x
                    for x in tokenize(remove_urls(message.content.lower()))
                    if x.strip()
                )
            )
        )
        for known_content in self.kernel.data["phishing_content"]:
            match = ratio(content, known_content)
            if match > 0.9:
                return {
                    "content": Message("report_phishing_errors_detected").translate(
                        self.kernel, interaction.locale
                    )
                }

        value = await self.kernel.database.incr(
            f"user:{interaction.user.id}:report:slowmode"
        )
        if value == 1:
            await self.kernel.database.expire(
                f"user:{interaction.user.id}:report:slowmode", REPORT_SLOWMODE_TTL
            )

        if value > REPORT_SLOWMODE_LIMIT:
            return {
                "content": Message("report_errors_cooldown").translate(
                    self.kernel, interaction.locale
                )
            }

        await self.kernel.database.set(
            f"message:{interaction.target_id}:reported", "1", ex=REPORT_MAXAGE
        )

        channel_id = 968594736720019597

        embed = hikari.Embed(
            title="Phishing report", description=message.content, color=0xE74C3C
        )
        embed.set_author(
            name=f"{interaction.user} ({interaction.user.id})",
            icon=interaction.user.make_avatar_url(ext="webp", size=64),
        )
        embed.set_footer(
            f"{message.author} ({message.author.id})",
            icon=message.author.make_avatar_url(ext="webp", size=64),
        )
        embed.add_field("Channel", f"<#{message.channel_id}>")

        guild = interaction.get_guild()
        if guild is None:
            embed.add_field("Guild", str(interaction.guild_id))
        else:
            embed.add_field("Guild", f"{guild.name} ({guild.id})")

        component = interaction.app.rest.build_message_action_row()
        (
            component.add_button(hikari.ButtonStyle.SUCCESS, "x-pr-ack")
            .set_label("Acknowledge report")
            .add_to_container()
        )
        (
            component.add_button(hikari.ButtonStyle.DANGER, "x-pr-invalid")
            .set_label("Invalid report")
            .add_to_container()
        )
        (
            component.add_button(
                hikari.ButtonStyle.DANGER, f"x-pr-ban/{interaction.user.id}"
            )
            .set_label("Ban user from reporting")
            .add_to_container()
        )

        await interaction.app.rest.create_message(
            channel_id, embed=embed, component=component
        )

        return {
            "content": Message("report_phishing_thanks").translate(
                self.kernel, interaction.locale
            )
        }

    async def acknowldge_phishing_report(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        await interaction.edit_message(
            interaction.message, "Report acknowledged.", components=[]
        )
        return {"content": ":+1:"}

    async def invalid_phishing_report(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        await interaction.delete_message(interaction.message)
        return {"content": ":+1:"}

    async def ban_user_from_phishing_reports(
        self, interaction: hikari.ComponentInteraction, user_id: str
    ) -> InteractionResponse:
        await self.kernel.database.sadd("report:phishing:banned", (user_id,))

        component = self.kernel.bot.rest.build_message_action_row()
        (
            component.add_button(hikari.ButtonStyle.SECONDARY, f"x-pr-unban/{user_id}")
            .set_label("Unban reporter")
            .add_to_container()
        )

        await interaction.edit_message(
            interaction.message, "Reporter banned.", component=component
        )
        return {"content": ":+1:"}

    async def unban_user_from_phishing_reports(
        self, interaction: hikari.ComponentInteraction, user_id: str
    ) -> InteractionResponse:
        await self.kernel.database.srem("report:phishing:banned", (user_id,))

        component = interaction.app.rest.build_message_action_row()
        (
            component.add_button(hikari.ButtonStyle.SUCCESS, "x-pr-ack")
            .set_label("Acknowledge report")
            .add_to_container()
        )
        (
            component.add_button(hikari.ButtonStyle.DANGER, "x-pr-invalid")
            .set_label("Invalid report")
            .add_to_container()
        )
        (
            component.add_button(
                hikari.ButtonStyle.DANGER, f"x-pr-ban/{interaction.user.id}"
            )
            .set_label("Ban user from reporting")
            .add_to_container()
        )

        await interaction.edit_message(
            interaction.message, "Reporter unbanned.", component=component
        )
        return {"content": ":+1:"}

    # Message reports

    async def create_message_report(
        self, interaction: hikari.CommandInteraction
    ) -> InteractionResponse:
        if interaction.guild_id is None:
            return {
                "content": Message("report_errors_guildonly").translate(
                    self.kernel, interaction.locale
                )
            }
        assert interaction.target_id is not None
        assert interaction.resolved is not None

        if (
            utc_datetime() - interaction.target_id.created_at
        ).total_seconds() > REPORT_MAXAGE:
            return {
                "content": Message("report_errors_tooold").translate(
                    self.kernel, interaction.locale
                )
            }
        elif await self.kernel.database.exists(
            (f"guild:{interaction.guild_id}:message:{interaction.target_id}:reported",)
        ):
            return {
                "content": Message("report_errors_already").translate(
                    self.kernel, interaction.locale
                )
            }

        message = interaction.resolved.messages.get(interaction.target_id, None)
        if message is None or message.content is None:
            return {
                "content": Message("report_errors_nomessage").translate(
                    self.kernel, interaction.locale
                )
            }
        elif message.author.is_bot:
            return {
                "content": Message("report_errors_nobot").translate(
                    self.kernel, interaction.locale
                )
            }
        elif message.author.id == interaction.user.id:
            return {
                "content": Message("report_errors_noself").translate(
                    self.kernel, interaction.locale
                )
            }

        config = await get_config(self.kernel.database, interaction.guild_id)
        entitlements = await get_entitlements(
            self.kernel.database, interaction.guild_id
        )

        if (
            not config["report_enabled"]
            or entitlements["plan"] < entitlements["report"]
        ):
            return {
                "content": Message("report_message_errors_disabled").translate(
                    self.kernel, interaction.locale
                )
            }

        guild = interaction.get_guild()
        assert guild is not None
        member = message.member
        if member is None:
            member = guild.get_member(message.author)
        if member is None:
            try:
                member = await self.kernel.bot.rest.fetch_member(
                    guild.id, message.author
                )
            except hikari.NotFoundError:
                pass

        if response := self.check_message_report_ok(
            guild,
            message.author if member is None else member,
            config,
            interaction.locale,
        ):
            return response

        component = self.kernel.bot.rest.build_modal_action_row()
        (
            component.add_text_input(
                "reason",
                Message("report_message_modal_label").translate(
                    self.kernel, interaction.locale
                ),
            )
            .set_style(hikari.TextInputStyle.PARAGRAPH)
            .set_min_length(2)
            .set_max_length(1000)
            .set_placeholder(
                Message("report_message_modal_placeholder").translate(
                    self.kernel, interaction.locale
                )
            )
            .add_to_container()
        )

        await interaction.create_modal_response(
            Message("report_message_modal_title").translate(
                self.kernel, interaction.locale
            ),
            f"r-modal/{message.id}",
            components=[component],
        )
        self.message_cache[message.id] = message

        return {}

    async def finalize_message_report(
        self, interaction: hikari.ModalInteraction, message_id: str
    ) -> InteractionResponse:
        assert interaction.guild_id
        assert interaction.guild_locale

        message = self.message_cache.get(int(message_id))
        if message is None or message.content is None:
            return {
                "content": Message("report_message_modal_errors_expired").translate(
                    self.kernel, interaction.locale
                )
            }

        config = await get_config(self.kernel.database, interaction.guild_id)
        entitlements = await get_entitlements(
            self.kernel.database, interaction.guild_id
        )

        if (
            not config["report_enabled"]
            or entitlements["plan"] < entitlements["report"]
        ):
            return {
                "content": Message("report_message_errors_disabled").translate(
                    self.kernel, interaction.locale
                )
            }

        guild = interaction.get_guild()
        assert guild is not None
        member = message.member
        if member is None:
            member = guild.get_member(message.author)
        if member is None:
            try:
                member = await self.kernel.bot.rest.fetch_member(
                    guild.id, message.author
                )
            except hikari.NotFoundError:
                pass

        if response := self.check_message_report_ok(
            guild,
            message.author if member is None else member,
            config,
            interaction.locale,
        ):
            return response

        value = await self.kernel.database.incr(
            f"user:{interaction.user.id}:report:slowmode"
        )
        if value == 1:  # first time
            await self.kernel.database.expire(
                f"user:{interaction.user.id}:report:slowmode",
                REPORT_SLOWMODE_TTL,
            )

        if value > REPORT_SLOWMODE_LIMIT:
            return {
                "content": Message("report_errors_cooldown").translate(
                    self.kernel, interaction.locale
                )
            }

        await self.kernel.database.set(
            f"message:{message.id}:reported", "1", ex=REPORT_MAXAGE
        )

        report_id = (
            base64.b64encode(message.id.to_bytes(8, "big"), altchars=b"  ")
            .decode()
            .replace(" ", "")
            .strip("=")
        )

        row = interaction.components[0]
        reason_input = row.components[0]

        embed = (
            hikari.Embed(
                title=Message("report_message_embed_title").translate(
                    self.kernel, interaction.guild_locale
                ),
                description=message.content,
                color=0xE74C3C,
            )
            .set_footer(
                f"{message.author} ({message.author.id})",
                icon=message.author.make_avatar_url(ext="webp", size=64),
            )
            .add_field(
                Message("report_message_embed_channel").translate(
                    self.kernel, interaction.guild_locale
                ),
                f"<#{message.channel_id}>",
                inline=True,
            )
            .add_field(
                Message("report_message_embed_id").translate(
                    self.kernel, interaction.guild_locale
                ),
                report_id,
                inline=True,
            )
        )

        reason = (
            hikari.Embed(
                description=reason_input.value,
                color=0xE74C3C,
            )
            .set_author(
                name=Message("report_message_embed_reason").translate(
                    self.kernel, interaction.guild_locale
                )
            )
            .set_footer(
                f"{interaction.user} ({interaction.user.id})",
                icon=interaction.user.make_avatar_url(ext="webp", size=64),
            )
        )

        components = [
            self.kernel.bot.rest.build_message_action_row(),
            self.kernel.bot.rest.build_message_action_row(),
        ]
        (
            components[0]
            .add_button(hikari.ButtonStyle.LINK, message.make_link(guild))
            .set_label(
                Message("report_message_button_jump").translate(
                    self.kernel, interaction.guild_locale
                )
            )
            .add_to_container()
        )
        (
            components[0]
            .add_button(hikari.ButtonStyle.SECONDARY, "r-a-delete")
            .set_label(
                Message("report_message_button_delete").translate(
                    self.kernel, interaction.guild_locale
                )
            )
            .add_to_container()
        )
        (
            components[1]
            .add_button(
                hikari.ButtonStyle.SECONDARY, f"r-a-timeout/{message.author.id}"
            )
            .set_label(
                Message("report_message_button_timeout").translate(
                    self.kernel, interaction.guild_locale
                )
            )
            .set_is_disabled(member is None)
            .add_to_container()
        )
        (
            components[1]
            .add_button(hikari.ButtonStyle.SECONDARY, f"r-a-kick/{message.author.id}")
            .set_label(
                Message("report_message_button_kick").translate(
                    self.kernel, interaction.guild_locale
                )
            )
            .set_is_disabled(member is None)
            .add_to_container()
        )
        (
            components[1]
            .add_button(hikari.ButtonStyle.SECONDARY, f"r-a-ban/{message.author.id}")
            .set_label(
                Message("report_message_button_ban").translate(
                    self.kernel, interaction.guild_locale
                )
            )
            .add_to_container()
        )

        await interaction.app.rest.create_message(
            int(config["report_channel"]),
            Message(
                "report_message_reportedby",
                {
                    "user": interaction.user.id,
                    "name": escape_markdown(str(interaction.user)),
                },
            ).translate(self.kernel, interaction.locale),
            embeds=[embed, reason],
            components=components,
        )

        return {
            "content": Message("report_message_thanks", {"id": report_id}).translate(
                self.kernel, interaction.locale
            )
        }

    def check_message_report_ok(
        self,
        guild: hikari.Guild,
        author: hikari.User | hikari.Member,
        config: ConfigType,
        locale: str,
    ) -> InteractionResponse | None:
        if author.id == guild.owner_id:
            return {
                "content": Message("report_message_errors_nostaff").translate(
                    self.kernel, locale
                )
            }

        if isinstance(author, hikari.Member):
            if is_moderator(author, guild, config):
                return {
                    "content": Message("report_message_errors_nostaff").translate(
                        self.kernel, locale
                    )
                }

        channel = guild.get_channel(int(config["report_channel"]))
        if channel is None or not isinstance(channel, hikari.TextableGuildChannel):
            return {
                "content": Message("report_message_errors_channelnotfound").translate(
                    self.kernel, locale
                )
            }

        me = guild.get_my_member()
        if me is None:
            return {
                "content": Message("report_message_errors_nomyself").translate(
                    self.kernel, locale
                )
            }
        elif me.communication_disabled_until() is not None:
            return {
                "content": Message("report_message_errors_noperms").translate(
                    self.kernel, locale
                )
            }

        perms = permissions_for(me, channel)
        if perms & hikari.Permissions.ADMINISTRATOR:
            pass
        elif perms & PERMS_SEND != PERMS_SEND:
            return {
                "content": Message("report_message_errors_noperms").translate(
                    self.kernel, locale
                )
            }

        return None

    async def delete_reported_message(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        assert interaction.guild_locale
        message_link_button = typing.cast(
            hikari.ButtonComponent,
            interaction.message.components[0].components[0],
        )
        assert message_link_button.url is not None
        message_link = message_link_button.url
        channel_id, message_id = map(int, message_link.split("/")[-2:])

        guild = interaction.get_guild()

        result = "report_action_delete_fail"
        if guild is not None:
            me = guild.get_my_member()
            channel = guild.get_channel(channel_id)
            if me is not None and channel is not None:
                perms = permissions_for(me, channel)
                if perms & (
                    hikari.Permissions.ADMINISTRATOR
                    | hikari.Permissions.MANAGE_MESSAGES
                ):
                    try:
                        await self.kernel.bot.rest.delete_message(
                            channel_id, message_id
                        )
                    except hikari.NotFoundError:
                        pass
                    else:
                        result = "report_action_delete_success"

        builders = components_to_builder(
            interaction.message.components, self.kernel.bot.rest
        )
        typing.cast(
            hikari.api.LinkButtonBuilder[hikari.api.MessageActionRowBuilder],
            builders[0].components[0],
        ).set_is_disabled(True)
        typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            builders[0].components[1],
        ).set_is_disabled(True)

        assert interaction.message.content
        reasons = interaction.message.content.split("\n")
        if len(reasons) >= 5:
            reasons.pop(1)
        reasons.append(
            Message(
                "report_action_delete_reason",
                {
                    "user": interaction.user.id,
                    "name": escape_markdown(str(interaction.user)),
                },
            ).translate(self.kernel, interaction.guild_locale)
        )

        await interaction.edit_message(
            interaction.message, "\n".join(reasons), components=builders
        )

        return {"content": Message(result).translate(self.kernel, interaction.locale)}

    async def timeout_reported_person(
        self, interaction: hikari.ComponentInteraction, user_id: str
    ) -> InteractionResponse:
        component = self.kernel.bot.rest.build_modal_action_row()
        (
            component.add_text_input(
                "duration",
                Message("report_action_timeout_modal_title").translate(
                    self.kernel, interaction.locale
                ),
            )
            .set_min_length(1)
            .set_max_length(100)
            .set_placeholder(
                Message("report_action_timeout_modal_placeholder").translate(
                    self.kernel, interaction.locale
                )
            )
            .set_style(hikari.TextInputStyle.PARAGRAPH)
            .add_to_container()
        )

        await interaction.create_modal_response(
            Message("report_action_timeout_modal_title").translate(
                self.kernel, interaction.locale
            ),
            f"r-a-timeout/{user_id}",
            component,
        )

        return {}

    async def finalize_timeout_reported_person(
        self, interaction: hikari.ModalInteraction, user_id: str
    ) -> InteractionResponse | None:
        assert interaction.message is not None
        assert interaction.guild_locale is not None
        guild = interaction.get_guild()
        assert guild is not None
        me = guild.get_my_member()
        if me is None:
            logger.warning(f"cant find myself in guild {interaction.guild_id}")
            return None  # this will just say "internal error"
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await self.kernel.bot.rest.fetch_member(guild, int(user_id))
            except hikari.NotFoundError:
                builders = components_to_builder(
                    interaction.message.components, self.kernel.bot.rest
                )
                typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    builders[1].components[0],
                ).set_is_disabled(True)
                typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    builders[1].components[1],
                ).set_is_disabled(True)
                await interaction.edit_message(interaction.message, components=builders)
                return {
                    "content": Message("report_action_errors_notfound").translate(
                        self.kernel, interaction.locale
                    )
                }

        my_top_role = me.get_top_role()
        top_role = member.get_top_role()
        config = await get_config(self.kernel.database, guild.id)
        if (
            my_top_role is not None
            and top_role is not None
            and top_role.position >= my_top_role.position
        ):
            builders = components_to_builder(
                interaction.message.components, self.kernel.bot.rest
            )
            for index in range(0, 3):
                typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    builders[1].components[index],
                ).set_is_disabled(True)
            await interaction.edit_message(interaction.message, components=builders)
            return {
                "content": Message("report_action_errors_noperms").translate(
                    self.kernel, interaction.locale
                )
            }
        elif is_moderator(member, guild, config):
            return {
                "content": Message("report_message_errors_nostaff").translate(
                    self.kernel, interaction.locale
                )
            }

        for role in me.get_roles():
            if role.permissions & (
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MODERATE_MEMBERS
            ):
                break
        else:
            builders = components_to_builder(
                interaction.message.components, self.kernel.bot.rest
            )
            typing.cast(
                hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
                builders[1].components[0],
            ).set_is_disabled(True)
            return {
                "content": Message("report_action_errors_noperms").translate(
                    self.kernel, interaction.locale
                )
            }

        row = interaction.components[0]
        duration_input = row.components[0]
        duration = text_to_duration(duration_input.value)
        if duration is None or duration > MAX_TIMEOUT_DURATION:
            return {
                "content": Message("report_action_timeout_errors_duration").translate(
                    self.kernel, interaction.locale
                )
            }

        timed_out_until = utc_datetime() + timedelta(seconds=duration)
        await member.edit(
            communication_disabled_until=timed_out_until,
            reason=Message(
                "report_action_timeout_auditlog",
                {"user": interaction.user.id, "name": interaction.user},
            ).translate(self.kernel, interaction.guild_locale),
        )

        assert interaction.message.content
        reasons = interaction.message.content.split("\n")
        if len(reasons) >= 5:
            reasons.pop(1)
        reasons.append(
            Message(
                "report_action_timeout_reason",
                {
                    "user": interaction.user.id,
                    "name": escape_markdown(str(interaction.user)),
                    "duration": duration_to_text(duration),
                    "timestamp": int(timed_out_until.timestamp()),
                },
            ).translate(self.kernel, interaction.guild_locale)
        )

        await interaction.edit_message(interaction.message, "\n".join(reasons))

        return {
            "content": Message(
                "report_action_timeout_success",
                {
                    "duration": duration_to_text(duration),
                    "timestamp": int(timed_out_until.timestamp()),
                },
            ).translate(self.kernel, interaction.locale)
        }

    async def kick_reported_person(
        self, interaction: hikari.ComponentInteraction, user_id: str
    ) -> InteractionResponse | None:
        assert interaction.message is not None
        assert interaction.guild_locale is not None
        guild = interaction.get_guild()
        assert guild is not None
        me = guild.get_my_member()
        if me is None:
            logger.warning(f"cant find myself in guild {interaction.guild_id}")
            return None  # this will just say "internal error"
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await self.kernel.bot.rest.fetch_member(guild, int(user_id))
            except hikari.NotFoundError:
                builders = components_to_builder(
                    interaction.message.components, self.kernel.bot.rest
                )
                typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    builders[1].components[0],
                ).set_is_disabled(True)
                typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    builders[1].components[1],
                ).set_is_disabled(True)
                await interaction.edit_message(interaction.message, components=builders)
                return {
                    "content": Message("report_action_errors_notfound").translate(
                        self.kernel, interaction.locale
                    )
                }

        my_top_role = me.get_top_role()
        top_role = member.get_top_role()
        config = await get_config(self.kernel.database, guild.id)
        if (
            my_top_role is not None
            and top_role is not None
            and top_role.position >= my_top_role.position
        ):
            builders = components_to_builder(
                interaction.message.components, self.kernel.bot.rest
            )
            for index in range(0, 3):
                typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    builders[1].components[index],
                ).set_is_disabled(True)
            await interaction.edit_message(interaction.message, components=builders)
            return {
                "content": Message("report_action_errors_noperms").translate(
                    self.kernel, interaction.locale
                )
            }
        elif is_moderator(member, guild, config):
            return {
                "content": Message("report_message_errors_nostaff").translate(
                    self.kernel, interaction.locale
                )
            }

        for role in me.get_roles():
            if role.permissions & (
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.KICK_MEMBERS
            ):
                break
        else:
            builders = components_to_builder(
                interaction.message.components, self.kernel.bot.rest
            )
            typing.cast(
                hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
                builders[1].components[1],
            ).set_is_disabled(True)
            await interaction.edit_message(interaction.message, components=builders)
            return {
                "content": Message("report_action_errors_noperms").translate(
                    self.kernel, interaction.locale
                )
            }

        await member.kick(
            reason=Message(
                "report_action_kick_auditlog",
                {"user": interaction.user.id, "name": interaction.user},
            ).translate(self.kernel, interaction.guild_locale)
        )

        assert interaction.message.content
        reasons = interaction.message.content.split("\n")
        if len(reasons) >= 5:
            reasons.pop(1)
        reasons.append(
            Message(
                "report_action_kick_reason",
                {
                    "user": interaction.user.id,
                    "name": escape_markdown(str(interaction.user)),
                },
            ).translate(self.kernel, interaction.guild_locale)
        )

        builders = components_to_builder(
            interaction.message.components, self.kernel.bot.rest
        )
        typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            builders[1].components[0],
        ).set_is_disabled(True)
        typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            builders[1].components[1],
        ).set_is_disabled(True)

        await interaction.edit_message(
            interaction.message, "\n".join(reasons), components=builders
        )

        return {
            "content": Message("report_action_kick_success").translate(
                self.kernel, interaction.locale
            )
        }

    async def ban_reported_person(
        self, interaction: hikari.ComponentInteraction, user_id: str
    ) -> InteractionResponse | None:
        assert interaction.message is not None
        assert interaction.guild_locale is not None
        guild = interaction.get_guild()
        assert guild is not None
        me = guild.get_my_member()
        if me is None:
            logger.warning(f"cant find myself in guild {interaction.guild_id}")
            return None  # this will just say "internal error"
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await self.kernel.bot.rest.fetch_member(guild, int(user_id))
            except hikari.NotFoundError:
                pass

        if member is not None:
            my_top_role = me.get_top_role()
            top_role = member.get_top_role()
            config = await get_config(self.kernel.database, guild.id)
            if (
                my_top_role is not None
                and top_role is not None
                and top_role.position >= my_top_role.position
            ):
                builders = components_to_builder(
                    interaction.message.components, self.kernel.bot.rest
                )
                for index in range(0, 3):
                    typing.cast(
                        hikari.api.InteractiveButtonBuilder[
                            hikari.api.MessageActionRowBuilder
                        ],
                        builders[1].components[index],
                    ).set_is_disabled(True)
                await interaction.edit_message(interaction.message, components=builders)
                return {
                    "content": Message("report_action_errors_noperms").translate(
                        self.kernel, interaction.locale
                    )
                }
            elif is_moderator(member, guild, config):
                return {
                    "content": Message("report_message_errors_nostaff").translate(
                        self.kernel, interaction.locale
                    )
                }

        for role in me.get_roles():
            if role.permissions & (
                hikari.Permissions.ADMINISTRATOR | hikari.Permissions.BAN_MEMBERS
            ):
                break
        else:
            builders = components_to_builder(
                interaction.message.components, self.kernel.bot.rest
            )
            typing.cast(
                hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
                builders[1].components[2],
            ).set_is_disabled(True)
            await interaction.edit_message(interaction.message, components=builders)
            return {
                "content": Message("report_action_errors_noperms").translate(
                    self.kernel, interaction.locale
                )
            }

        await self.kernel.bot.rest.ban_user(
            guild.id,
            int(user_id),
            reason=Message(
                "report_action_ban_auditlog",
                {"user": interaction.user.id, "name": interaction.user},
            ).translate(self.kernel, interaction.guild_locale),
            delete_message_days=1,
        )

        assert interaction.message.content
        reasons = interaction.message.content.split("\n")
        if len(reasons) >= 5:
            reasons.pop(1)
        reasons.append(
            Message(
                "report_action_ban_reason",
                {
                    "user": interaction.user.id,
                    "name": escape_markdown(str(interaction.user)),
                },
            ).translate(self.kernel, interaction.guild_locale)
        )

        builders = components_to_builder(
            interaction.message.components, self.kernel.bot.rest
        )
        for index in range(0, 3):
            typing.cast(
                hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
                builders[1].components[index],
            ).set_is_disabled(True)

        message_link_button = typing.cast(
            hikari.ButtonComponent,
            interaction.message.components[0].components[0],
        )
        assert message_link_button.url is not None
        message_link = message_link_button.url
        message_id = hikari.Snowflake(message_link.split("/")[-1])

        if (utc_datetime() - message_id.created_at).total_seconds() < 60 * 60 * 24:
            typing.cast(
                hikari.api.LinkButtonBuilder[hikari.api.MessageActionRowBuilder],
                builders[0].components[0],
            ).set_is_disabled(True)
            typing.cast(
                hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
                builders[0].components[1],
            ).set_is_disabled(True)

        await interaction.edit_message(
            interaction.message, "\n".join(reasons), components=builders
        )

        return {
            "content": Message("report_action_ban_success").translate(
                self.kernel, interaction.locale
            )
        }
