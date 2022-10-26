import string

factors = {
    "y": 60 * 60 * 24 * 365,
    "w": 60 * 60 * 24 * 7,
    "d": 60 * 60 * 24,
    "h": 60 * 60,
    "m": 60,
    "s": 1,
}


def text_to_duration(text: str) -> int | None:
    duration, buffer = 0, ""
    for t in text:
        if t.isdigit():
            buffer += t
        elif t in factors:
            duration += int(buffer if buffer else "1") * factors[t]
            buffer = ""
        elif t in string.whitespace or t == ",":
            pass
        else:
            return None
    if buffer:
        duration += int(buffer)
    return duration


def duration_to_text(duration: int, separator: str = "") -> str:
    if not duration:
        return "0s"

    text = []
    for t, factor in factors.items():
        if duration >= factor:
            duration, value = duration % factor, duration // factor
            text.append(f"{value:,}{t}")

    return separator.join(text)
