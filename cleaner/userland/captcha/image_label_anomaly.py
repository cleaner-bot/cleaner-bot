import random
import typing

from PIL import Image  # type: ignore

from .dataset import datasets

__all__ = ["ImageLabelAnomalyTask", "generate"]
MIN_REQUIRED = 100


class ImageLabelAnomalyTask(typing.NamedTuple):
    solution: int
    image: Image.Image


def generate(
    rng: random.Random | None = None,
    prompt: str | None = None,
    grid: tuple[int, int] = (3, 3),
) -> ImageLabelAnomalyTask:
    if rng is None:
        rng = random.Random()

    rows, columns = grid
    if prompt is None:
        prompt = rng.choice(
            tuple(k for k, v in datasets.items() if len(v) > MIN_REQUIRED)
        )

    total = rows * columns
    wrong_image_list = []
    for wrong_prompt, dataset in datasets.items():
        if wrong_prompt != prompt:
            wrong_image_list.extend(dataset)

    images = rng.sample(datasets[prompt], k=total - 1)
    anomaly_image = rng.choice(wrong_image_list)
    all_images = images + [anomaly_image]
    rng.shuffle(all_images)

    solution = next(
        filter(lambda x: x[1], ((i, x in images) for i, x in enumerate(all_images)))
    )
    collage = Image.new("RGB", (rows * 100, columns * 100))
    for index, image_path in enumerate(all_images):
        image = Image.open(image_path)
        collage.paste(image, ((index % rows) * 100, (index // rows) * 100))

    return ImageLabelAnomalyTask(solution[0], collage)
