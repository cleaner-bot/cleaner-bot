import typing


def tokenize(text: str) -> typing.Generator[str, None, None]:
    buffer: list[str] = []
    last_type = None
    for char in text:
        if char_type(char) != last_type:
            if buffer:
                yield "".join(buffer)
            buffer.clear()
            last_type = char_type(char)
        buffer.append(char)
    if buffer:
        yield "".join(buffer)


def char_type(char: str) -> int:
    if char.isalpha():
        return 0
    elif char.isdigit():
        return 1
    elif not char.isprintable():
        return 2  # whitespace
    return 3
