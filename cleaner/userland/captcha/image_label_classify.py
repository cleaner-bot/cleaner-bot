import io
import random
import typing

from PIL import Image  # type: ignore

from .dataset import datasets

__all__ = ["ImageLabelClassificationTask", "generate"]


class ImageLabelClassificationTask(typing.NamedTuple):
    solution: str
    decoys: tuple[str, ...]
    image: Image.Image


def generate(
    rng: random.Random | None = None, prompt: str | None = None, decoys: int = 4
) -> ImageLabelClassificationTask:
    if rng is None:
        rng = random.Random()

    if prompt is None:
        prompt = rng.choice(tuple(datasets.keys()))

    image_binary = rng.choice(datasets[prompt]).read_bytes()
    image = Image.open(io.BytesIO(image_binary))

    decoy_pool = list(datasets.keys())
    decoy_pool.remove(prompt)

    decoy_names = rng.sample(decoy_pool, k=decoys)

    return ImageLabelClassificationTask(prompt, tuple(decoy_names), image)
