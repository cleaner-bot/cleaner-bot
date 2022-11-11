import asyncio
import base64
import random
import string
import typing

import hikari
from captcha_rs import CaptchaBuilder
from hikari.internal.time import utc_datetime

from .._types import InteractionResponse, KernelType
from ..helpers.binding import complain_if_none, safe_call
from ..helpers.localization import Message

RANDOM_SEED = "UxTDoaJ/+A6Tld87W8HO++/apO6kBc3vjrQx1BzyzuA"


class TextCaptchaVerificationService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        components: dict[
            str, typing.Callable[..., typing.Awaitable[InteractionResponse | None]]
        ] = {
            "v-chl-t-select": self.on_select_captcha_simple,
            "v-chl-t-different": self.on_different_captcha_simple,
            "v-chl-t-info": self.on_info_captcha_simple,
        }

        self.kernel.interactions["components"].update(components)

        self.kernel.bindings[
            "verification:textcaptcha:issue"
        ] = self.issue_simple_captcha_verification

    async def issue_simple_captcha_verification(
        self, solved: int, locale: str
    ) -> InteractionResponse:
        captcha = (
            CaptchaBuilder()
            .length(5 if random.random() > 0.2 else 6)
            .width(random.randint(280, 320))
            .height(random.randint(100, 120))
            .dark_mode(True)
            .complexity(random.randint(3, 7))
            .build()
        )

        text = captcha.text.upper()
        button_labels_set = set(text)
        while len(button_labels_set) < 10:
            button_labels_set.add(random.choice(string.ascii_uppercase))
        button_labels = "".join(button_labels_set)

        rnd = random.Random()
        rnd.seed(button_labels + RANDOM_SEED)
        otp = rnd.randbytes(len(button_labels))
        encrypted_text = base64.urlsafe_b64encode(
            bytes([x ^ otp[i] for i, x in enumerate(text.encode())])
        ).decode()

        components = self.build_components(
            solved, button_labels, encrypted_text, locale
        )

        return {
            "content": Message(
                "verification_text_content", {"remaining": len(captcha.text)}
            ).translate(self.kernel, locale),
            "components": components,
            "attachments": [base64.b64decode(captcha.base_img.split(",")[1])],
        }

    async def on_select_captcha_simple(
        self,
        interaction: hikari.ComponentInteraction,
        raw_solved: str,
        button_labels: str,
        label: str,
        encrypted_text: str,
    ) -> InteractionResponse | None:
        guild = interaction.get_guild()
        assert guild is not None
        assert interaction.member is not None

        solved = int(raw_solved)
        rnd = random.Random()
        rnd.seed(button_labels + RANDOM_SEED)
        otp = rnd.randbytes(len(button_labels))
        decrypted_text = bytes(
            [x ^ otp[i] for i, x in enumerate(base64.urlsafe_b64decode(encrypted_text))]
        ).decode()

        is_correct = label == decrypted_text[0]

        age = (utc_datetime() - interaction.user.id.created_at).total_seconds()
        sleep_factor = 0 if age > 15552000 else (1 - age / 15552000)

        if sleep_factor:
            await asyncio.sleep(sleep_factor * 3)

        if is_correct:
            if len(decrypted_text) > 1:  # correct and more to do
                text = decrypted_text[1:]
                rnd.seed(button_labels + RANDOM_SEED)
                otp = rnd.randbytes(len(button_labels))
                new_encrypted_text = base64.urlsafe_b64encode(
                    bytes([x ^ otp[i] for i, x in enumerate(text.encode())])
                ).decode()
                components = self.build_components(
                    solved, button_labels, new_encrypted_text, interaction.locale
                )

                await interaction.edit_message(
                    interaction.message,
                    content=Message(
                        "verification_text_content", {"remaining": len(text)}
                    ).translate(self.kernel, interaction.locale),
                    components=components,
                    attachments=None,
                )
                return {}

            solved += 1

        else:
            await self.kernel.database.hincrby(
                f"guild:{guild.id}:verification", str(interaction.user.id), 1
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
                await interaction.edit_message(interaction.message, **response)
                return {}

        return None

    async def on_different_captcha_simple(
        self, interaction: hikari.ComponentInteraction, solved: str
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
                await interaction.edit_message(interaction.message, **response)
                return {}

        return None

    def build_components(
        self, solved: int, button_labels: str, encrypted_text: str, locale: str
    ) -> list[hikari.api.ActionRowBuilder]:
        components: list[hikari.api.ActionRowBuilder] = []
        for index, label in enumerate(button_labels):
            if index % 5 == 0:
                components.append(self.kernel.bot.rest.build_action_row())

            (
                components[-1]
                .add_button(
                    hikari.ButtonStyle.SECONDARY,
                    f"v-chl-t-select/{solved}/{button_labels}/{label}/{encrypted_text}",
                )
                .set_label(label)
                .add_to_container()
            )

        components.append(self.kernel.bot.rest.build_action_row())

        (
            components[-1]
            .add_button(hikari.ButtonStyle.SECONDARY, f"v-chl-t-different/{solved}")
            .set_label(
                Message("verification_text_different").translate(self.kernel, locale)
            )
            .add_to_container()
        )
        (
            components[-1]
            .add_button(hikari.ButtonStyle.SECONDARY, "v-chl-t-info")
            .set_label("?")
            .add_to_container()
        )

        return components

    async def on_info_captcha_simple(
        self, interaction: hikari.ComponentInteraction
    ) -> InteractionResponse:
        await interaction.edit_message(
            interaction.message,
            Message("verification_text_info").translate(
                self.kernel, interaction.locale
            ),
        )

        return {}
