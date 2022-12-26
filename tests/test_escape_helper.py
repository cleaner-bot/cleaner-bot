import pytest

from cleaner.userland.helpers.escape import escape_markdown


@pytest.mark.parametrize(
    "text,expected",
    (
        ("test", "test"),
        ("tea*st", "tea\\*st"),
        ("tea_st_", "tea\\_st\\_"),
        ("~~test~~", "\\~\\~test\\~\\~"),
        ("`test`", "\\`test\\`"),
    ),
)
def test_escape_markdown(text: str, expected: str) -> None:
    assert expected == escape_markdown(text)
