ESCAPES = "*_`~<@"
ESCAPE_DICT = str.maketrans({key: f"\\{key}" for key in ESCAPES})


def escape_markdown(name: str) -> str:
    return name.translate(ESCAPE_DICT)
