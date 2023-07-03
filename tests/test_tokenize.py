import pytest

from cleaner.userland.helpers.tokenizer import tokenize


@pytest.mark.parametrize("input, expected", (
    ("hello world", ("hello", "world")),
    ("123.456", ("123", "456")),
    ("test123", ("test", "123")),
))
def test_tokenize(input: str, expected: tuple[str, ...]) -> None:
    assert tuple(tokenize(input)) == expected
