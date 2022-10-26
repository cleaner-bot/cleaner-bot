import typing

from coredis import Redis
from hikari import GatewayBot


class HypervisorType(typing.Protocol):
    bot: GatewayBot
    database: Redis[bytes]

    def load_kernel(self) -> bool:
        ...

    def unload_kernel(self) -> None:
        ...

    def load_recovery(self) -> bool:
        ...

    def unload_recovery(self) -> None:
        ...

    def reload(self) -> None:
        ...

    def is_kernel_loaded(self) -> bool:
        ...

    def is_recovery_loaded(self) -> bool:
        ...
