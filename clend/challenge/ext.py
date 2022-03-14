import asyncio
import typing
import hashlib
import logging

import hikari
from hikari.internal.time import utc_datetime

from cleaner_conf.guild.config import Config

from ..bot import TheCleaner
from ..shared.protect import protect
from ..shared.sub import listen as pubsub_listen, Message


logger = logging.getLogger(__name__)


class ChallengeExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner):
        self.bot = bot
        self.listeners = [
            (hikari.InteractionCreateEvent, self.on_interaction_create),
        ]
        self.task = None

    def on_load(self):
        self.task = asyncio.create_task(protect(self.verifyd))

    def on_unload(self):
        if self.task is not None:
            self.task.cancel()

    async def on_interaction_create(self, event: hikari.InteractionCreateEvent):
        interaction = event.interaction
        if not isinstance(interaction, hikari.ComponentInteraction):
            return
        elif not interaction.custom_id.startswith("challenge"):
            return

        age = (utc_datetime() - interaction.created_at).total_seconds()
        if age > 3:
            logger.error(f"received interaction that is older than 3s ({age:.3f}s)")
        elif age > 1:
            logger.warning(f"received interaction that is older than 1s ({age:.3f}s)")
        else:
            logger.debug(f"got interaction with age {age:.3f}s")

        try:
            await self.create_flow(interaction)
        except Exception as e:
            logger.exception("Error occured during component interaction", exc_info=e)
            await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    "**Internal error**: Something went wrong on our end.\n"
                    "**Please contact support!**"
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

    async def create_flow(self, interaction: hikari.ComponentInteraction):
        guild = interaction.get_guild()
        if guild is None:
            return

        config = self.get_config(guild.id)
        if config is None:
            logger.warning(f"uncached guild settings: {guild.id}")
            url = "https://cleaner.leodev.xyz/discord"
            component = self.bot.bot.rest.build_action_row()
            (
                component.add_button(hikari.ButtonStyle.LINK, url)
                .set_label("Support")
                .add_to_container()
            )

            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    "**Internal error**: We have no information "
                    "about the server you are in.\n"
                    "**Please contact support!**"
                ),
                component=component,
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        if not config.challenge_interactive_enabled:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    "Interactive challenges have been disabled by the server "
                    "staff on the Dashboard."
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif not config.challenge_interactive_role:
            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    f"Server staff has not selected a role for me to {act}.\n"
                    f"Contact server staff and inform them that they have not "
                    f"completed the setup yet."
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        member = interaction.member
        if member is None or (
            (config.challenge_interactive_role not in member.role_ids)
            == config.challenge_interactive_take_role
        ):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content="You are already verified.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        role = guild.get_role(config.challenge_interactive_role)
        if role is None:
            act = "take" if config.challenge_interactive_take_role else "give"
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    f"I can not find the role I am supposed to {act}. "
                    f"Maybe it has been deleted?\n"
                    f"Contact server staff and inform them to select an "
                    f"up-to-date role."
                ),
            )
        elif role.is_managed:
            act = "take" if config.challenge_interactive_take_role else "give"
            # TODO: make a help desk article
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    f"I can not {act} the role {role.mention} because it is "
                    f"managed (e.g. a bot role, the server booster role, or "
                    f"part of a different integration)"
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        me = guild.get_my_member()
        if me is None:
            url = "https://cleaner.leodev.xyz/discord"
            component = self.bot.bot.rest.build_action_row()
            (
                component.add_button(hikari.ButtonStyle.LINK, url)
                .set_label("Support")
                .add_to_container()
            )

            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    "**Internal error**: I can not find myself.\n"
                    "Please try again in a few minutes.\n\n"
                    "If this problem persists please contact support."
                ),
                component=component,
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        top_role = me.get_top_role()
        if top_role is not None and role.position >= top_role.position:
            act = "take" if config.challenge_interactive_take_role else "give"
            # TODO: make a help desk article
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    f"The role I am supposed to {act} is above me in the role "
                    f"hierarchy and therefore I can not give it.\n"
                    f"Contact server staff and ask them to move me above the "
                    f"{role.mention} role in the role settings."
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        for my_role in me.get_roles():
            if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                break
            elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                break
        else:
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    "I do not have permission to give roles :(\n"
                    "Contact server staff and ask them to give me the "
                    "`ADMINISTRATOR` or `MANAGE ROLES` permission."
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        flow = hashlib.sha256(interaction.id.to_bytes(8, "big")).hexdigest()
        logger.debug(
            f"created flow for {interaction.user.id}@{interaction.guild_id}: {flow}"
        )

        await self.bot.database.set(
            f"challenge:flow:{flow}:user", interaction.user.id, ex=300
        )
        await self.bot.database.set(
            f"challenge:flow:{flow}:guild", interaction.guild_id, ex=300
        )

        url = f"https://cleaner.leodev.xyz/challenge?flow={flow}"

        component = self.bot.bot.rest.build_action_row()
        (
            component.add_button(hikari.ButtonStyle.LINK, url)
            .set_label("Solve challenge")
            .add_to_container()
        )

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            content=(
                "Click the button below and follow the instructions on "
                "the website to verify.\n"
                "*You have 5 minutes before the link becomes invalid*"
            ),
            component=component,
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def verifyd(self):
        pubsub = self.bot.database.pubsub()
        await pubsub.subscribe("pubsub:challenge-verify")
        async for event in pubsub_listen(pubsub):
            if not isinstance(event, Message):
                continue

            flow = event.data.decode()

            logger.debug(f"flow has been solved: {flow}")

            user_id = await self.bot.database.get(f"challenge:flow:{flow}:user")
            guild_id = await self.bot.database.get(f"challenge:flow:{flow}:guild")

            guild = self.bot.bot.cache.get_guild(int(guild_id))
            if guild is None:
                logger.warning(f"uncached guild: {guild_id}")
                continue
            config = self.get_config(guild.id)

            if config is None:
                logger.warning("uncached guild settings")
                continue

            role = guild.get_role(config.challenge_interactive_role)
            if role is None or role.is_managed:
                continue

            me = guild.get_my_member()
            if me is None:
                continue

            top_role = me.get_top_role()
            if top_role is not None and role.position >= top_role.position:
                continue

            for my_role in me.get_roles():
                if my_role.permissions & hikari.Permissions.ADMINISTRATOR:
                    break
                elif my_role.permissions & hikari.Permissions.MANAGE_ROLES:
                    break
            else:
                continue

            routine = self.bot.bot.rest.add_role_to_member
            if config.challenge_interactive_take_role:
                routine = self.bot.bot.rest.remove_role_from_member

            # TODO: error handler
            await routine(guild.id, int(user_id), config.challenge_interactive_role)

    def get_config(self, guild_id: int) -> typing.Optional[Config]:
        conf = self.bot.extensions.get("clend.conf", None)
        if conf is None:
            logger.warning("unable to find clend.conf extension")
            return None
        return conf.get_config(guild_id)
