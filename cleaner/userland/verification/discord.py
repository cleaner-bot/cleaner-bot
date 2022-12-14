import asyncio
import io
import os
import random
import string
import typing
from base64 import urlsafe_b64decode, urlsafe_b64encode

import hikari
from hikari.internal.time import utc_datetime

from .._types import InteractionResponse, KernelType
from ..captcha import (
    image_label_binary,
    image_label_classify,
    image_label_transcribe,
    mask_image,
)
from ..helpers.binding import complain_if_none, safe_call
from ..helpers.builders import components_to_builder
from ..helpers.localization import Message

IMAGE_LABEL_BINARY = "image_label_binary"
IMAGE_LABEL_CLASSIFY = "image_label_classify"
IMAGE_LABEL_TRANSCRIBE = "image_label_transcribe"


class DiscordVerificationService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "v-chl-ilb-select": self.btn_image_label_binary_select,
            "v-chl-ilb-submit": self.btn_image_label_binary_submit,
            "v-chl-ilc-select": self.btn_image_label_classify_select,
            "v-chl-ilt-select": self.btn_image_label_transcribe_select,
            "v-chl-ilt-delete": self.btn_image_label_transcribe_delete,
            "v-chl-ilt-submit": self.btn_image_label_transcribe_submit,
            "v-chl-i-different": self.btn_different_captcha,
            "v-chl-i-info": self.btn_info,
        }

        self.kernel.interactions["components"].update(components)

        self.kernel.bindings[
            "verification:discord:issue"
        ] = self.issue_discord_verification

    async def issue_discord_verification(
        self, member: hikari.Member, solved: int, locale: str
    ) -> InteractionResponse | None:
        tasks = (IMAGE_LABEL_BINARY, IMAGE_LABEL_CLASSIFY, IMAGE_LABEL_TRANSCRIBE)
        task_name = tasks[
            int(member.id + utc_datetime().timestamp()) // 300 % len(tasks)
        ]

        if task_name == IMAGE_LABEL_BINARY:
            return await self.issue_image_label_binary(solved, locale)
        elif task_name == IMAGE_LABEL_CLASSIFY:
            return await self.issue_image_label_classify(solved, locale)
        elif task_name == IMAGE_LABEL_TRANSCRIBE:
            return await self.issue_image_label_transcribe(solved, locale)
        return None

    # image label binary
    async def issue_image_label_binary(
        self, solved: int, locale: str
    ) -> InteractionResponse:
        loop = asyncio.get_running_loop()
        task = await loop.run_in_executor(None, image_label_binary.generate)

        solution_int = 0
        for i, value in enumerate(task.solution):
            if value:
                solution_int |= 1 << i

        mask_image(task.image, random.randint(20, 60))
        data = io.BytesIO()
        task.image.save(data, "jpeg", quality=40)

        raw_secret = solution_int.to_bytes(2, "big")

        seed = "".join(random.choices(string.ascii_letters, k=10))
        rnd = random.Random()
        rnd.seed(seed + os.environ["CUSTOM_ID_ENCRYPTION_KEY"])
        otp = rnd.randbytes(2)
        secret = urlsafe_b64encode(
            bytes([x ^ otp[i] for i, x in enumerate(raw_secret)])
        ).decode()

        components = self.image_label_binary_components(solved, locale, seed, secret)

        prompt_name = Message(f"image_objects_{task.prompt}").translate(
            self.kernel, locale
        )
        return {
            "content": Message(
                "image_label_binary_task", {"prompt": prompt_name}
            ).translate(self.kernel, locale),
            "components": components,
            "attachments": [data.getvalue()],
        }

    def image_label_binary_components(
        self, solved: int, locale: str, seed: str, secret: str
    ) -> list[hikari.api.MessageActionRowBuilder]:
        rows: list[hikari.api.MessageActionRowBuilder] = []
        for row in range(3):
            rows.append(self.kernel.bot.rest.build_message_action_row())
            for column in range(3):
                (
                    rows[-1]
                    .add_button(
                        hikari.ButtonStyle.SECONDARY, f"v-chl-ilb-select/{row}/{column}"
                    )
                    .set_label("\u200B")
                    .add_to_container()
                )

        rows.append(self.kernel.bot.rest.build_message_action_row())
        (
            rows[-1]
            .add_button(
                hikari.ButtonStyle.PRIMARY, f"v-chl-ilb-submit/{solved}/{seed}/{secret}"
            )
            .set_label(
                Message("image_label_binary_submit").translate(self.kernel, locale)
            )
            .set_is_disabled(True)
            .add_to_container()
        )
        (
            rows[-1]
            .add_button(hikari.ButtonStyle.SECONDARY, f"v-chl-i-info/{solved}/1")
            .set_label("?")
            .add_to_container()
        )

        return rows

    async def btn_image_label_binary_select(
        self, interaction: hikari.ComponentInteraction, raw_row: str, raw_column: str
    ) -> InteractionResponse:
        row, column = int(raw_row), int(raw_column)
        components = components_to_builder(
            interaction.message.components, self.kernel.bot.rest
        )
        button = typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            components[row].components[column],
        )
        new_style = (
            hikari.ButtonStyle.SUCCESS
            if button.style == hikari.ButtonStyle.SECONDARY
            else hikari.ButtonStyle.SECONDARY
        )
        button._style = new_style  # type: ignore

        total_selected = 0
        for i in range(0, 3):
            for j in range(0, 3):
                button = typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    components[i].components[j],
                )
                if button.style == hikari.ButtonStyle.SUCCESS:
                    total_selected += 1

        button = typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            components[3].components[0],
        )
        button.set_is_disabled(total_selected < 2)

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            components=components,
        )

        return {}

    async def btn_image_label_binary_submit(
        self,
        interaction: hikari.ComponentInteraction,
        raw_solved: str,
        seed: str,
        raw_secret: str,
    ) -> InteractionResponse | None:
        rnd = random.Random()
        rnd.seed(seed + os.environ["CUSTOM_ID_ENCRYPTION_KEY"])
        otp = rnd.randbytes(2)
        secret = bytes(
            [x ^ otp[i] for i, x in enumerate(urlsafe_b64decode(raw_secret))]
        )
        secret_int = int.from_bytes(secret, "big")

        selected_int = 0
        for i in range(0, 3):
            row = interaction.message.components[i]
            for j in range(0, 3):
                button = typing.cast(hikari.ButtonComponent, row.components[j])
                if button.style == hikari.ButtonStyle.SUCCESS:
                    selected_int |= 1 << (3 * i + j)

        return await self.on_solve(
            interaction, int(raw_solved), selected_int == secret_int, 3
        )

    # image label classify
    async def issue_image_label_classify(
        self, solved: int, locale: str
    ) -> InteractionResponse:
        loop = asyncio.get_running_loop()
        task = await loop.run_in_executor(None, image_label_classify.generate)

        choices = [task.solution] + list(task.decoys)
        random.shuffle(choices)

        raw_secret = choices.index(task.solution).to_bytes(2, "big")
        seed = "".join(random.choices(string.ascii_letters, k=10))
        rnd = random.Random()
        rnd.seed(seed + os.environ["CUSTOM_ID_ENCRYPTION_KEY"])
        otp = rnd.randbytes(2)
        secret = urlsafe_b64encode(
            bytes([x ^ otp[i] for i, x in enumerate(raw_secret)])
        ).decode()

        rows: list[hikari.api.MessageActionRowBuilder] = []
        for i, choice in enumerate(choices):
            if i % 5 == 0:
                rows.append(self.kernel.bot.rest.build_message_action_row())
            prompt_name = Message(f"image_objects_{choice}").translate(
                self.kernel, locale
            )
            (
                rows[-1]
                .add_button(
                    hikari.ButtonStyle.SECONDARY,
                    f"v-chl-ilc-select/{solved}/{i}/{seed}/{secret}",
                )
                .set_label(prompt_name)
                .add_to_container()
            )

        rows.append(self.kernel.bot.rest.build_message_action_row())
        (
            rows[-1]
            .add_button(hikari.ButtonStyle.SECONDARY, f"v-chl-i-info/{solved}/1")
            .set_label("?")
            .add_to_container()
        )

        mask_image(task.image, random.randint(60, 100))
        data = io.BytesIO()
        task.image.save(data, "jpeg", quality=40)

        return {
            "content": Message("image_label_classify_task").translate(
                self.kernel, locale
            ),
            "components": rows,
            "attachments": [data.getvalue()],
        }

    async def btn_image_label_classify_select(
        self,
        interaction: hikari.ComponentInteraction,
        raw_solved: str,
        raw_index: str,
        seed: str,
        raw_secret: str,
    ) -> InteractionResponse | None:
        rnd = random.Random()
        rnd.seed(seed + os.environ["CUSTOM_ID_ENCRYPTION_KEY"])
        otp = rnd.randbytes(2)
        secret = bytes(
            [x ^ otp[i] for i, x in enumerate(urlsafe_b64decode(raw_secret))]
        )
        secret_index = int.from_bytes(secret, "big")
        index = int(raw_index)

        return await self.on_solve(
            interaction, int(raw_solved), index == secret_index, 1
        )

    # image label transcribe
    async def issue_image_label_transcribe(
        self, solved: int, locale: str
    ) -> InteractionResponse:
        loop = asyncio.get_running_loop()
        task = await loop.run_in_executor(None, image_label_transcribe.generate)

        mask_image(task.image, random.randint(60, 100))
        data = io.BytesIO()
        task.image.save(data, "jpeg", quality=40)

        letters = set(task.solution.upper())
        while len(letters) < 10:
            letters.update(random.sample(string.ascii_uppercase, k=10 - len(letters)))

        raw_secret = task.solution.encode()
        seed = "".join(random.choices(string.ascii_letters, k=10))
        rnd = random.Random()
        rnd.seed(seed + os.environ["CUSTOM_ID_ENCRYPTION_KEY"])
        otp = rnd.randbytes(len(raw_secret))
        secret = urlsafe_b64encode(
            bytes([x ^ otp[i] for i, x in enumerate(raw_secret)])
        ).decode()

        rows = self.image_label_transcribe_components(
            solved, locale, letters, seed, secret
        )
        preview = " ".join(["` `"] * len(raw_secret))

        return {
            "content": Message(
                "image_label_transcribe_task", {"input": preview}
            ).translate(self.kernel, locale),
            "components": rows,
            "attachments": [data.getvalue()],
        }

    def image_label_transcribe_components(
        self, solved: int, locale: str, letters: set[str], seed: str, secret: str
    ) -> list[hikari.api.MessageActionRowBuilder]:
        rows: list[hikari.api.MessageActionRowBuilder] = []

        for i, letter in enumerate(letters):
            if i % 5 == 0:
                rows.append(self.kernel.bot.rest.build_message_action_row())
            (
                rows[-1]
                .add_button(hikari.ButtonStyle.SECONDARY, f"v-chl-ilt-select/{letter}")
                .set_label(letter)
                .add_to_container()
            )

        rows.append(self.kernel.bot.rest.build_message_action_row())
        (
            rows[-1]
            .add_button(hikari.ButtonStyle.DANGER, "v-chl-ilt-delete")
            .set_label("↩️")
            .set_is_disabled(True)
            .add_to_container()
        )
        (
            rows[-1]
            .add_button(
                hikari.ButtonStyle.PRIMARY,
                f"v-chl-ilt-submit/{solved}//{seed}/{secret}",
            )
            .set_label(
                Message("image_label_transcribe_submit").translate(self.kernel, locale)
            )
            .set_is_disabled(True)
            .add_to_container()
        )
        (
            rows[-1]
            .add_button(hikari.ButtonStyle.SECONDARY, f"v-chl-i-info/{solved}/0")
            .set_label("?")
            .add_to_container()
        )

        return rows

    async def btn_image_label_transcribe_select(
        self, interaction: hikari.ComponentInteraction, letter: str
    ) -> InteractionResponse:
        components = components_to_builder(
            interaction.message.components, self.kernel.bot.rest
        )
        delete = typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            components[2].components[0],
        )
        submit = typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            components[2].components[1],
        )
        settings = submit.custom_id.split("/")
        settings[2] += letter
        submit._custom_id = "/".join(settings)  # type: ignore

        max_length = len(urlsafe_b64decode(settings[-1]))
        delete.set_is_disabled(False)
        submit.set_is_disabled(len(settings[2]) < max_length)
        if len(settings[2]) >= max_length:
            for i in range(0, 2):
                for j in range(0, 5):
                    btn = typing.cast(
                        hikari.api.InteractiveButtonBuilder[
                            hikari.api.MessageActionRowBuilder
                        ],
                        components[i].components[j],
                    )
                    btn.set_is_disabled(True)

        preview = " ".join([f"`{x}`" for x in settings[2].ljust(max_length)])

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            content=Message(
                "image_label_transcribe_task", {"input": preview}
            ).translate(self.kernel, interaction.locale),
            components=components,
        )
        return {}

    async def btn_image_label_transcribe_delete(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        components = components_to_builder(
            interaction.message.components, self.kernel.bot.rest
        )
        delete = typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            components[2].components[0],
        )
        submit = typing.cast(
            hikari.api.InteractiveButtonBuilder[hikari.api.MessageActionRowBuilder],
            components[2].components[1],
        )
        settings = submit.custom_id.split("/")
        settings[2] = settings[2][:-1]
        submit._custom_id = "/".join(settings)  # type: ignore

        max_length = len(urlsafe_b64decode(settings[-1]))
        delete.set_is_disabled(len(settings[2]) == 0)
        submit.set_is_disabled(True)
        for i in range(0, 2):
            for j in range(0, 5):
                btn = typing.cast(
                    hikari.api.InteractiveButtonBuilder[
                        hikari.api.MessageActionRowBuilder
                    ],
                    components[i].components[j],
                )
                btn.set_is_disabled(False)

        preview = " ".join([f"`{x}`" for x in settings[2].ljust(max_length)])

        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            content=Message(
                "image_label_transcribe_task", {"input": preview}
            ).translate(self.kernel, interaction.locale),
            components=components,
        )
        return {}

    async def btn_image_label_transcribe_submit(
        self,
        interaction: hikari.ComponentInteraction,
        raw_solved: str,
        letters: str,
        seed: str,
        raw_secret: str,
    ) -> InteractionResponse | None:
        rnd = random.Random()
        rnd.seed(seed + os.environ["CUSTOM_ID_ENCRYPTION_KEY"])
        secret_bytes = urlsafe_b64decode(raw_secret)
        otp = rnd.randbytes(len(secret_bytes))
        secret = bytes([x ^ otp[i] for i, x in enumerate(secret_bytes)]).decode()

        return await self.on_solve(
            interaction, int(raw_solved), secret.upper() == letters, 3
        )

    # general stuff
    async def on_solve(
        self,
        interaction: hikari.ComponentInteraction,
        solved: int,
        correct: bool,
        difficulty: int,
    ) -> InteractionResponse | None:
        guild = interaction.get_guild()
        assert guild is not None, "how tf"

        if correct:
            solved += difficulty
        else:
            await self.kernel.database.hincrby(
                f"guild:{interaction.guild_id}:verification",
                str(interaction.user.id),
                difficulty,
            )

        if issue_verification := complain_if_none(
            self.kernel.bindings.get("verification:issue"), "verification:issue"
        ):
            if (
                response := await safe_call(
                    issue_verification(interaction, guild, solved, False)
                )
            ) is not None:
                response.setdefault("attachments", None)
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE, **response
                )
                return {}

        return None

    async def btn_different_captcha(
        self, interaction: hikari.ComponentInteraction, solved: str, raw_message_id: str
    ) -> InteractionResponse | None:
        guild = interaction.get_guild()
        assert guild is not None
        assert interaction.member is not None

        await self.kernel.database.hincrby(
            f"guild:{guild.id}:verification", str(interaction.member.id), 1
        )

        if issue_verification := complain_if_none(
            self.kernel.bindings.get("verification:issue"), "verification:issue"
        ):
            if (
                response := await safe_call(
                    issue_verification(interaction, guild, int(solved), True)
                )
            ) is not None:
                response.setdefault("attachments", None)
                await interaction.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE, **response
                )
                await interaction.delete_message(int(raw_message_id))
                return {}

        return None

    async def btn_info(
        self, interaction: hikari.ComponentInteraction, solved: str, disclaimer: str
    ) -> InteractionResponse:
        component = self.kernel.bot.rest.build_message_action_row()
        (
            component.add_button(
                hikari.ButtonStyle.PRIMARY,
                f"v-chl-i-different/{solved}/{interaction.message.id}",
            )
            .set_label(
                Message("verification_discord_info_button").translate(
                    self.kernel, interaction.locale
                )
            )
            .add_to_container()
        )
        if disclaimer == "1":
            (
                component.add_button(
                    hikari.ButtonStyle.SECONDARY,
                    f"v-chl-i-report/{interaction.message.id}",
                )
                .set_label(
                    Message("verification_discord_info_disclaimer_button").translate(
                        self.kernel, interaction.locale
                    )
                )
                .add_to_container()
            )

        return {
            "content": Message("verification_discord_info").translate(
                self.kernel, interaction.locale
            )
            + (
                "\n\n"
                + Message("verification_discord_info_disclaimer").translate(
                    self.kernel, interaction.locale
                )
                if disclaimer == "1"
                else ""
            ),
            "component": component,
        }
