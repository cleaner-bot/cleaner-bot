from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from .._types import KernelType


class Message(typing.NamedTuple):
    translate_key: str
    variables: dict[str, typing.Any] | None = None

    def translate(self, kernel: KernelType, locale: str) -> str:
        if self.variables is None:
            return kernel.translate(locale, self.translate_key)
        return kernel.translate(locale, self.translate_key, **self.variables)
