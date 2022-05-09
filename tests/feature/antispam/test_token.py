import random
import string
from types import SimpleNamespace
from unittest import mock

from clend.guild.components.mitigations.token import detection


def use_detection(data):
    guild = mock.Mock()
    guild_data = mock.Mock()
    guild_data.config.slowmode_exceptions = []
    guild.get_data.return_value = guild_data
    messages = [SimpleNamespace(content=x, channel_id=0) for x in data]
    return detection(messages[0], messages[1:], guild)


def rand_string(length=None):
    if length is None:
        length = random.randint(16, 32)
    return "".join(random.choice(string.ascii_letters) for _ in range(length))


def test_token_simple():
    messages = ["hello world"] * 100
    mitigation = use_detection(messages)
    assert set(mitigation.tokens) == {"hello", "world"}


def test_token_one():
    random.seed(0)
    messages = ["hello world " + rand_string(32) for _ in range(100)]
    mitigation = use_detection(messages)
    assert set(mitigation.tokens) == {"hello", "world"}


def test_token_chatter():
    random.seed(0)
    messages = [
        "hello world " + rand_string() if random.random() > 0.1 else rand_string(32)
        for _ in range(100)
    ]
    mitigation = use_detection(messages)
    assert set(mitigation.tokens) == {"hello", "world"}
