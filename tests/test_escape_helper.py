import pytest

from cleaner.userland.helpers.escape import escape_markdown


@pytest.mark.parametrize(
    "text,expected",
    (
        ("test", "test"),
        ("te*st", "te\\*st"),
        ("te_st_", "te\\_st\\_"),
        ("~~test~~", "\\~\\~test\\~\\~"),
        ("`test`", "\\`test\\`"),
    ),
)
def test_escape_markdown(text: str, expected: str) -> None:
    assert expected == escape_markdown(text)
