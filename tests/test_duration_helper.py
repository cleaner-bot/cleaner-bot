import pytest

from cleaner.userland.helpers.duration import duration_to_text, text_to_duration


@pytest.mark.parametrize(
    "text,duration",
    (
        ("", 0),
        ("s", 1),
        ("1s", 1),
        ("ss", 2),
        ("10s", 10),
        ("s10ss", 12),
        ("m", 60),
        ("ms", 61),
        ("sm", 61),
        ("60m", 3600),
        ("h", 3600),
        ("1,,,,,00,,,,,0s", 1_000),
        ("15w5d11h47m4s", 0x91AAB8),
        ("1", 1),
        ("X", None),
        (" ", 0),
        ("1 h", 3600),
        ("         \t\t\n1                                                ", 1),
    ),
)
def test_text_to_duration(text: str, duration: int) -> None:
    assert text_to_duration(text) == duration


@pytest.mark.parametrize(
    "duration,text",
    (
        (0, "0s"),
        (1, "1s"),
        (2, "2s"),
        (60, "1m"),
        (61, "1m1s"),
        (62, "1m2s"),
        (120, "2m"),
        (121, "2m1s"),
        (122, "2m2s"),
        (0x91AAB8, "15w5d11h47m4s"),
    ),
)
def test_duration_to_text(duration: int, text: str) -> None:
    assert duration_to_text(duration) == text


def test_duration_to_text_with_separator() -> None:
    assert duration_to_text(123, " ") == "2m 3s"
