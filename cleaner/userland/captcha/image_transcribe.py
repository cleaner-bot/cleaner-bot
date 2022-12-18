import io
import typing
from base64 import b64decode

from captcha_rs import CaptchaBuilder
from PIL import Image  # type: ignore

__all__ = ["ImageLabelTranscriptionTask", "generate"]


class ImageLabelTranscriptionTask(typing.NamedTuple):
    solution: str
    image: Image.Image


def generate(
    length: int = 5,
    width: int = 300,
    height: int = 100,
    complexity: int = 4,
    dark_mode: bool = True,
) -> ImageLabelTranscriptionTask:
    captcha = (
        CaptchaBuilder()
        .length(length)
        .width(width)
        .height(height)
        .dark_mode(dark_mode)
        .complexity(complexity)
        .build()
    )
    image_binary = b64decode(captcha.base_img.split(",")[1])
    image = Image.open(io.BytesIO(image_binary))
    return ImageLabelTranscriptionTask(captcha.text, image)
