import asyncio
import typing

import msgpack  # type: ignore

from .._types import KernelType
from ..helpers.binding import complain_if_none, safe_call


class RPCConsumerService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.tasks = [asyncio.create_task(self.runner_task(), name="consumer.rpc")]

    def on_unload(self) -> None:
        for task in self.tasks:
            task.cancel()

    async def runner_task(self) -> None:
        pubsub = self.kernel.database.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe("pubsub:rpc")
        call_id: str
        fn_name: str
        args: tuple[typing.Any]
        while True:
            message = await pubsub.get_message()
            if message is not None and message["type"] == "message":
                call_id, fn_name, args = msgpack.unpackb(
                    message["data"], use_list=False
                )
                asyncio.create_task(
                    self.call_rpc(call_id, fn_name, args), name="consumer.rpccall"
                )

    async def call_rpc(
        self, call_id: str, fn_name: str, args: tuple[typing.Any]
    ) -> None:
        await self.kernel.database.publish(f"pubsub:rpc:{call_id}", "ACK")

        response = {"ok": False, "message": "Function Not Found", "data": None}
        if rpc := complain_if_none(self.kernel.rpc.get(fn_name), fn_name):
            if resp := await safe_call(rpc(*args)):  # type: ignore
                response = resp
            else:
                response["message"] = "Internal error"

        await self.kernel.database.publish(
            f"pubsub:rpc:{call_id}", msgpack.packb(response)
        )
