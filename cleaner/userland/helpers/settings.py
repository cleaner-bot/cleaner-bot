import typing

import msgpack  # type: ignore
from coredis import Redis

from .._types import ConfigType, EntitlementsType, KernelType


async def get_config(kernel: KernelType, guild_id: int) -> ConfigType:
    raw_config = await kernel.database.hgetall(f"guild:{guild_id}:config")
    return {**kernel.data["config"], **decode_settings(raw_config)}  # type: ignore


async def set_config(
    database: Redis[bytes], guild_id: int, config: dict[str, typing.Any]
) -> None:
    raw_config = typing.cast(
        dict[str | bytes, str | bytes | int | float],
        {k: msgpack.packb(v) for k, v in config.items()},
    )
    await database.hset(f"guild:{guild_id}:config", raw_config)


async def get_entitlements(kernel: KernelType, guild_id: int) -> EntitlementsType:
    raw_entitlements = await kernel.database.hgetall(f"guild:{guild_id}:entitlements")
    return {
        **kernel.data["entitlements"],  # type: ignore
        **decode_settings(raw_entitlements),
    }


async def set_entitlements(
    database: Redis[bytes], guild_id: int, entitlements: dict[str, typing.Any]
) -> None:
    raw_entitlements = typing.cast(
        dict[str | bytes, str | bytes | int | float],
        {k: msgpack.packb(v) for k, v in entitlements.items()},
    )
    await database.hset(f"guild:{guild_id}:entitlements", raw_entitlements)


def decode_settings(dictionary: dict[bytes, bytes]) -> dict[str, str | int | bool]:
    return {key.decode(): msgpack.unpackb(value) for key, value in dictionary.items()}
