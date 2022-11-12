import random
import typing

from PIL import Image  # type: ignore

from .dataset import datasets

__all__ = ["ImageLabelBinaryTask", "generate"]


class ImageLabelBinaryTask(typing.NamedTuple):
    prompt: str
    solution: tuple[bool, ...]
    image: Image.Image


def generate(
    rng: random.Random | None = None,
    prompt: str | None = None,
    grid: tuple[int, int] = (3, 3),
) -> ImageLabelBinaryTask:
    if rng is None:
        rng = random.Random()

    rows, columns = grid
    if prompt is None:
        prompt = rng.choice(tuple(datasets.keys()))
    total = rows * columns
    correct = rng.randint(
        1 if total < 3 else 2, total - 1 if total < 9 else int(total * 2 / 3)
    )
    wrong = total - correct
    wrong_image_list = []
    for wrong_prompt, dataset in datasets.items():
        if wrong_prompt != prompt:
            wrong_image_list.extend(dataset)

    correct_images = rng.sample(datasets[prompt], k=correct)
    wrong_images = rng.sample(wrong_image_list, k=wrong)
    all_images = correct_images + wrong_images
    rng.shuffle(all_images)

    solution = tuple(x in correct_images for x in all_images)
    collage = Image.new("RGB", (rows * 100, columns * 100))
    for index, image_path in enumerate(all_images):
        image = Image.open(image_path)
        collage.paste(image, ((index % rows) * 100, (index // rows) * 100))

    return ImageLabelBinaryTask(prompt, solution, collage)
