import logging
import typing

import hikari
from hikari.internal.time import utc_datetime

from .._types import ConfigType, InteractionResponse, KernelType, RPCResponse
from ..helpers.escape import escape_markdown
from ..helpers.invite import generate_invite
from ..helpers.localization import Message
from ..helpers.permissions import DANGEROUS_PERMISSIONS, permissions_for
from ..helpers.settings import get_config
from ..helpers.task import complain_if_none, safe_call

logger = logging.getLogger(__name__)
REQUIRED_TO_SEND = (
    hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.EMBED_LINKS
)


class VerificationService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "challenge": self.challenge_create,  # legacy
            "v-verify": self.verification_create,
            "v-info": self.verification_info,
        }

        self.kernel.interactions["components"].update(components)

        self.kernel.bindings["verification:issue"] = self.issue_verification
        self.kernel.bindings["verification:check"] = self.check_circumstances
        self.kernel.bindings["verification:solved"] = self.verification_solved
        self.kernel.rpc["verification:post-message"] = self.rpc_post_message

    async def challenge_create(
        self, interaction: hikari.ComponentInteraction, verify: str | None = None
    ) -> InteractionResponse | None:
        return await self.verification_create(interaction)

    async def verification_create(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse | None:
        # verify argument is legacy stuff from long long ago
        if (
            interaction.guild_id is None
            or interaction.member is None
            or (guild := interaction.get_guild()) is None
        ):
            await interaction.execute(
                content=Message("interaction_error_guildonly").translate(
                    self.kernel, interaction.locale
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return {}

        if response := await self.issue_verification(interaction, guild):
            return response

        return None

    async def verification_info(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        component = self.kernel.bot.rest.build_message_action_row()
        component.add_link_button(
            generate_invite(self.kernel.bot, True, True),
            label=Message("verification_info_protect").translate(
                self.kernel, interaction.locale
            ),
        )
        component.add_link_button(
            "https://docs.cleanerbot.xyz/legal/impressum/",
            label=Message("verification_info_legal").translate(
                self.kernel, interaction.locale
            ),
        )

        return {
            "content": Message("verification_info").translate(
                self.kernel, interaction.locale
            ),
            "flags": hikari.MessageFlag.EPHEMERAL | hikari.MessageFlag.SUPPRESS_EMBEDS,
            "component": component,
        }

    async def check_circumstances(
        self,
        guild: hikari.Guild,
        member: hikari.Member,
        locale: str,
        config: ConfigType,
    ) -> InteractionResponse | None:
        """
        Make sure we can actually do what we are trying to do.
        """
        if not config["verification_enabled"]:
            return {
                "content": Message("verification_errors_disabled").translate(
                    self.kernel, locale
                )
            }

        give_or_take = Message(
            "verification_action_"
            + ("take" if config["verification_take_role"] else "give")
        ).translate(self.kernel, locale)
        role_id = int(config["verification_role"])
        if role_id == 0:
            logger.debug(f"failed verification in {guild.id}; no role set")
            return {
                "content": Message(
                    "verification_errors_norole", {"action": give_or_take}
                ).translate(self.kernel, locale),
                "components": [],
            }
        elif (role_id not in member.role_ids) == config["verification_take_role"]:
            return {
                "content": Message(
                    "verification_errors_verified", {"action": give_or_take}
                ).translate(self.kernel, locale),
                "components": [],
            }

        role = guild.get_role(role_id)
        if role is None:
            logger.debug(f"failed verification in {guild.id}; role is gone")
            return {
                "content": Message(
                    "verification_errors_role_gone", {"action": give_or_take}
                ).translate(self.kernel, locale),
                "components": [],
            }
        elif role.is_managed:
            logger.debug(f"failed verification in {guild.id}; role is managed")
            return {
                "content": Message(
                    "verification_errors_role_managed", {"action": give_or_take}
                ).translate(self.kernel, locale),
                "components": [],
            }
        elif role.id == guild.id:
            logger.debug(
                f"failed verification in {guild.id}; role is the everyone role"
            )
            return {
                "content": Message(
                    "verification_errors_role_everyone", {"action": give_or_take}
                ).translate(self.kernel, locale),
                "components": [],
            }
        elif role.permissions & DANGEROUS_PERMISSIONS:
            logger.debug(
                f"failed verification in {guild.id}; role has dangerous permissions"
            )
            component = self.kernel.bot.rest.build_message_action_row()
            component.add_link_button(
                "https://docs.cleanerbot.xyz/misc/roles/dangerous-permissions",
                label=Message("verification_errors_role_dangerous_link").translate(
                    self.kernel, locale
                ),
            )
            return {
                "content": Message(
                    "verification_errors_role_dangerous", {"action": give_or_take}
                ).translate(self.kernel, locale),
                "component": component,
            }

        me = guild.get_my_member()
        if me is None:
            logger.debug(f"failed verification in {guild.id}; me is gone")
            return {
                "content": Message("verification_errors_no_myself").translate(
                    self.kernel, locale
                )
            }
        elif (
            top_role := me.get_top_role()
        ) is not None and role.position >= top_role.position:
            logger.debug(f"failed verification in {guild.id}; role is higher than me")
            component = self.kernel.bot.rest.build_message_action_row()
            component.add_link_button(
                "https://docs.cleanerbot.xyz/misc/roles#role-hierarchy",
                label=Message("verification_errors_hierarchy_link").translate(
                    self.kernel, locale
                ),
            )
            return {
                "content": Message(
                    "verification_errors_hierarchy",
                    {"action": give_or_take, "role": role.id},
                ).translate(self.kernel, locale),
                "component": component,
            }

        for role in me.get_roles():
            if role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            logger.debug(f"failed verification in {guild.id}; me no perms")
            return {
                "content": Message(
                    "verification_errors_noperms", {"action": give_or_take}
                ).translate(self.kernel, locale),
                "components": [],
            }

        return None

    async def issue_verification(
        self,
        interaction: hikari.ComponentInteraction,
        guild: hikari.Guild,
        solved: int = 0,
        force_external: bool = False,
    ) -> InteractionResponse | None:
        assert interaction.member
        config = await get_config(self.kernel, guild.id)

        if response := await self.check_circumstances(
            guild, interaction.member, interaction.locale, config
        ):
            return response

        danger = 0
        if danger_level := complain_if_none(
            self.kernel.bindings.get("http:danger_level"), "http:danger_level"
        ):
            danger = danger_level(guild.id)

        verification_level = danger
        if level := await self.kernel.database.hget(
            f"guild:{guild.id}:verification", str(interaction.user.id)
        ):
            verification_level += int(level)

        if verification_level >= 15:
            force_external = True

        age = (utc_datetime() - interaction.user.id.created_at).total_seconds()
        if age < config["verification_age"]:
            verification_level += 1

        if solved >= max(3, min(15, verification_level)):
            assert interaction.member
            return await self.verification_solved(
                interaction.member, config, interaction.locale
            )

        if danger >= 100:
            return {
                "content": Message("verification_disabled").translate(
                    self.kernel, interaction.locale
                ),
                "components": [],
            }

        if danger >= 20 or force_external:
            if issue_external_verification := complain_if_none(
                self.kernel.bindings.get("verification:external:issue"),
                "verification:external:issue",
            ):
                if (
                    response := await safe_call(
                        issue_external_verification(interaction)
                    )
                ) is not None:
                    return response

        if issue_discord_verification := complain_if_none(
            self.kernel.bindings.get("verification:discord:issue"),
            "verification:discord:issue",
        ):
            if (
                response := await safe_call(
                    issue_discord_verification(
                        interaction.member, solved, interaction.locale
                    )
                )
            ) is not None:
                return response

        return None

    async def verification_solved(
        self, member: hikari.Member, config: ConfigType, locale: str
    ) -> InteractionResponse:
        logger.debug(f"verification solved by {member.id} in {member.guild_id}")

        await self.kernel.database.hdel(
            f"guild:{member.guild_id}:verification", (str(member.id),)
        )

        role_id = int(config["verification_role"])
        if config["verification_take_role"]:
            await member.remove_role(role_id)
        else:
            await member.add_role(role_id)

        if config["logging_enabled"]:
            if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
                message = Message(
                    "log_verified",
                    {"user": str(member.id), "name": escape_markdown(str(member.user))},
                )
                await safe_call(log(member.guild_id, message, None, None))

        return {
            "content": Message("verification_verified").translate(self.kernel, locale),
            "components": [],
        }

    async def rpc_post_message(self, guild_id: int, channel_id: int) -> RPCResponse:
        logger.debug(f"posting message {guild_id=} {channel_id=}")
        channel = self.kernel.bot.cache.get_guild_channel(channel_id)
        if (
            channel is None
            or channel.guild_id != guild_id
            or not isinstance(channel, hikari.TextableGuildChannel)
        ):
            return {"ok": False, "message": "Channel not found", "data": None}

        guild = self.kernel.bot.cache.get_guild(guild_id)
        if guild is None or (me := guild.get_my_member()) is None:
            return {"ok": False, "message": "cache issues", "data": None}

        perms = permissions_for(me, channel)
        if (
            perms & hikari.Permissions.ADMINISTRATOR == 0
            and perms & REQUIRED_TO_SEND != REQUIRED_TO_SEND
        ) or me.communication_disabled_until() is not None:
            return {
                "ok": False,
                "message": "no permissions to post in channel",
                "data": None,
            }

        await channel.send(**self.build_message())  # type: ignore
        return {"ok": True, "message": "OK", "data": None}

    def build_message(self) -> InteractionResponse:
        component = self.kernel.bot.rest.build_message_action_row()
        component.add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            "v-verify",
            label="I am not a robot",
            emoji="🕵️",
        )
        component.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, "v-info", label="?"
        )
        return {"content": "", "embeds": [], "component": component}
