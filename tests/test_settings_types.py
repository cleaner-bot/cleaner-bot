import typing

from cleaner.userland._types import ConfigType, EntitlementsType
from cleaner.userland.helpers.settings import default_config, default_entitlements


def test_config_types() -> None:
    expected = {
        k: typing.ForwardRef("list[str]" if isinstance(v, list) else type(v).__name__)
        for k, v in default_config.items()
    }
    expected["auth_roles"] = typing.ForwardRef("dict[str, list[str]]")
    assert ConfigType.__annotations__ == expected


def test_entitlements_types() -> None:
    expected = {
        k: typing.ForwardRef(type(v).__name__) for k, v in default_entitlements.items()
    }
    assert EntitlementsType.__annotations__ == expected
