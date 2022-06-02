from __future__ import annotations

import typing


class ResultDict(typing.TypedDict):
    rules: dict[str, Stat]
    traffic: dict[str, Stat]
    categories: dict[str, Stat]
    challenges: dict[str, Stat]
    stats: dict[str, int]


class Stat(typing.TypedDict):
    total: int
    previous: int
    now: int
