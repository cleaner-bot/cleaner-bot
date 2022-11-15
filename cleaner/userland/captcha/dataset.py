from pathlib import Path

__all__ = ["origin", "datasets", "load_dataset"]


origin = Path("~/cleaner-captcha-data").expanduser()

datasets: dict[str, list[Path]] = {}


def load_dataset() -> None:
    if not origin.exists():
        return
    datasets.clear()
    for prompt in origin.iterdir():
        if prompt.name.startswith("."):
            continue
        dataset = datasets[prompt.name] = []
        for file in prompt.iterdir():
            if file.name.startswith(".") or not file.name.endswith(".jpg"):
                continue
            dataset.append(file)


load_dataset()
