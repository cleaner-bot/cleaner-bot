import numpy as np
from PIL import Image  # type: ignore

from . import image_label_binary, image_label_classify, image_label_transcribe

__all__ = [
    "image_label_binary",
    "image_label_classify",
    "image_label_transcribe",
    "mask_image",
]


def mask_image(image: Image.Image, complexity: int = 80) -> Image.Image:
    overlay = np.random.random_sample((image.size[1], image.size[0], 4))
    overlay *= np.array((255, 255, 255, complexity))
    overlay = overlay.astype("uint8")
    overlay_image = Image.fromarray(overlay, "RGBA")
    image.paste(overlay_image, (0, 0), overlay_image)
    return image
