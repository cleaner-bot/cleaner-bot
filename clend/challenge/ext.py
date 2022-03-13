import asyncio
import typing
import hashlib
import logging

import hikari

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
        if (
            not isinstance(interaction, hikari.ComponentInteraction)
            or interaction.guild_id is None
        ):
            return

        custom_id = interaction.custom_id.split("/")
        if custom_id[0] != "challenge":
            return

        config = self.get_config(interaction.guild_id)
        if config is None:
            url = "https://cleaner.leodev.xyz/discord"
            component = event.app.rest.build_action_row()
            (
                component.add_button(hikari.ButtonStyle.LINK, url)
                .set_label("Support")
                .add_to_container()
            )

            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                content=(
                    "Something went wrong on our end. We have no information "
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
                    f"Contact server staff and inform them that they haven't "
                    f"completed the setup yet."
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        role = config.challenge_interactive_role
        member = interaction.member
        if member is None or (
            role not in member.role_ids == config.challenge_interactive_take_role
        ):
            return await interaction.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE, content="You are already verified."
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

        component = event.app.rest.build_action_row()
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
            print(event)

            flow = event.data.decode()

            logger.debug(f"flow has been solved: {flow}")

            user_id = await self.bot.database.get(f"challenge:flow:{flow}:user")
            guild_id = await self.bot.database.get(f"challenge:flow:{flow}:guild")

            guild = self.bot.bot.cache.get_guild(int(guild_id))
            config = self.get_config(guild.id)

            if config is None:
                logger.warning("uncached guild settings")
                continue
            elif not config.challenge_interactive_role:
                logger.warning("role id 0 for interactive challenge")
                continue
            # TODO: permissions checks

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
