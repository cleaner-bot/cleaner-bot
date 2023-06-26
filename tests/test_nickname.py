from types import SimpleNamespace

import hikari
import pytest

from cleaner.userland.dehoist import DehoistService


@pytest.mark.parametrize(
    "nickname, global_name, username, expected",
    (
        (None, None, "hello", hikari.UNDEFINED),
        (None, "Hello", "hello", hikari.UNDEFINED),
        (None, "Hello", "!hello", hikari.UNDEFINED),
        ("Hello!", "Hello", "hello", hikari.UNDEFINED),
        (None, None, "!hello", "hello"),
        (None, "!hell", "hello", "hell"),
        (None, "!hell", "!hello", "hell"),
        (None, "!", "hello", "hello_"),
        (None, "!", "!hello", "hello"),
        (None, "!", "!!", "dehoisted"),
        ("hello", "!", "!!", hikari.UNDEFINED),
        ("!Hello", "hello", "hello", "Hello"),
        ("!hello", "hello", "hell", None),
        ("!", "hello", "hell", None),
        ("!", "hello", "hello", None),
        ("!!", "!!", "dehoisted", "dehoisted_"),
    ),
)
def test_nicknames(
    nickname: str | None,
    global_name: str | None,
    username: str,
    expected: hikari.UndefinedNoneOr[str],
) -> None:
    fake = SimpleNamespace(
        nickname=nickname,
        global_name=global_name,
        username=username,
        display_name=nickname or global_name or username,
    )

    assert DehoistService.nickname(None, fake) == expected  # type: ignore
