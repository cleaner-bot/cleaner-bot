import logging

import hikari

from ._types import InteractionResponse, KernelType, RPCResponse
from .helpers.binding import complain_if_none, safe_call
from .helpers.escape import escape_markdown
from .helpers.invite import generate_invite
from .helpers.localization import Message
from .helpers.permissions import DANGEROUS_PERMISSIONS, permissions_for
from .helpers.settings import get_config

logger = logging.getLogger(__name__)
REQUIRED_TO_SEND = (
    hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.EMBED_LINKS
)


class SuperVerificationService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel
        self.kernel.rpc["super-verification:verify"] = self.rpc_verify
        self.kernel.rpc["super-verification:post-message"] = self.rpc_post_message

    async def rpc_verify(self, guild_id: int, user_id: int) -> RPCResponse:
        deleted = await self.kernel.database.hdel(
            f"guild:{guild_id}:timelimit", (str(user_id),)
        )
        if not deleted:
            return {"ok": False, "message": "already verified", "data": None}

        guild = self.kernel.bot.cache.get_guild(int(guild_id))
        if guild is None or (me := guild.get_my_member()) is None:
            return {"ok": False, "message": "guild not found", "data": None}

        config = await get_config(self.kernel, guild_id)

        if not config["super_verification_enabled"]:
            return {
                "ok": False,
                "message": "super verification is not enabled",
                "data": None,
            }

        role = guild.get_role(int(config["super_verification_role"]))
        if (
            role is None
            or role.is_managed
            or role.position == 0
            or role.permissions & DANGEROUS_PERMISSIONS
        ):
            return {
                "ok": False,
                "message": "cant or wont give role",
                "data": None,
            }

        top_role = me.get_top_role()
        if top_role is not None and role.position >= top_role.position:
            return {
                "ok": False,
                "message": "role too high",
                "data": None,
            }

        for my_role in me.get_roles():
            if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            return {
                "ok": False,
                "message": "no perms to give role",
                "data": None,
            }

        await self.kernel.bot.rest.add_role_to_member(guild.id, user_id, role.id)

        if config["logging_enabled"]:
            user = self.kernel.bot.cache.get_user(user_id)
            if user is None:
                user = await self.kernel.bot.rest.fetch_user(user_id)

            if log := complain_if_none(self.kernel.bindings.get("log"), "log"):
                message = Message(
                    "log_verified",
                    {"user": str(user.id), "name": escape_markdown(str(user))},
                )
                await safe_call(log(guild_id, message, None, None), True)

        return {"ok": True, "message": "OK", "data": None}

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

        await channel.send(**self.build_message(guild_id))  # type: ignore
        return {"ok": True, "message": "OK", "data": None}

    def build_message(self, guild_id: int) -> InteractionResponse:
        embed = hikari.Embed(
            title=":detective: Click to verify you are human",
            url=generate_invite(self.kernel.bot, False, True, f"verify#{guild_id}"),
        ).set_author(
            name="Need help?",
            url="https://docs.cleanerbot.xyz/help/super-verification/",
        )
        # component = self.kernel.bot.rest.build_message_action_row()
        # (
        #     component.add_button(
        #         hikari.ButtonStyle.LINK,
        #         generate_invite(self.kernel.bot, False, True, f"verify#{guild_id}"),
        #     )
        #     .set_label("Verify")
        #     .set_emoji("🕵️")
        #     .add_to_container()
        # )
        # (
        #     component.add_button(
        #         hikari.ButtonStyle.LINK,
        #         "https://docs.cleanerbot.xyz/help/super-verification/",
        #     )
        #     .set_label("?")
        #     .add_to_container()
        # )
        return {"content": "", "embeds": [embed]}
