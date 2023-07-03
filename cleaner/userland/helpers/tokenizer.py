import typing

from string import whitespace, punctuation

TOO_GENERAL = (2, 3)


def tokenize(text: str) -> typing.Generator[str, None, None]:
    buffer: list[str] = []
    last_type = None
    for char in text:
        if char_type(char) != last_type:
            if buffer and last_type not in TOO_GENERAL:
                yield "".join(buffer)
            buffer.clear()
            last_type = char_type(char)
        buffer.append(char)
    if buffer and last_type not in TOO_GENERAL:
        yield "".join(buffer)


def char_type(char: str) -> int:
    if char.isalpha():
        return 0
    elif char.isdigit():
        return 1
    elif char in whitespace:
        return 2
    elif char in punctuation:
        return 3
    return 4
