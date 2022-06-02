import random
import string
from types import SimpleNamespace
from unittest import mock

from clend.guild.components.mitigations.token import TokenMessageMitigation, detection


def use_detection(data: list[str]) -> TokenMessageMitigation | None:
    guild = mock.Mock()
    guild_data = mock.Mock()
    guild_data.config.slowmode_exceptions = []
    guild.get_data.return_value = guild_data
    messages = [SimpleNamespace(content=x, channel_id=0) for x in data]
    return detection(messages[0], messages[1:], guild)  # type: ignore


def rand_string(length: int | None = None) -> str:
    if length is None:
        length = random.randint(16, 32)
    return "".join(random.choice(string.ascii_letters) for _ in range(length))


def test_token_simple() -> None:
    messages = ["hello world"] * 100
    mitigation = use_detection(messages)
    assert mitigation is not None
    assert set(mitigation.tokens) == {"hello", "uorld"}


def test_token_one() -> None:
    random.seed(0)
    messages = ["hello world " + rand_string(32) for _ in range(100)]
    mitigation = use_detection(messages)
    assert mitigation is not None
    assert set(mitigation.tokens) == {"hello", "uorld"}


def test_token_chatter() -> None:
    random.seed(0)
    messages = [
        "hello world " + rand_string() if random.random() > 0.1 else rand_string(32)
        for _ in range(100)
    ]
    mitigation = use_detection(messages)
    assert mitigation is not None
    assert set(mitigation.tokens) == {"hello", "uorld"}
