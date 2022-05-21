import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from secretclient import request

load_dotenv(Path("~/.cleaner/env/bot").expanduser())


def _load_secrets():
    fields = (
        "sentry/dsn",
        "discord/bot-token",
        "discord/client-id",
        "redis/password",
        "topgg/api-token",
    )
    identity = Path("~/.cleaner/identity").expanduser().read_text()
    for key, value in request(
        bytes.fromhex(identity), fields, os.getenv("secret/host")
    ).items():
        os.environ[key] = value


_load_secrets()
del _load_secrets

from clend.app import TheCleanerApp  # noqa: E402

try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


token = os.getenv("discord/bot-token")
if token is None:
    print("Token not found.")
    exit(1)


sentry_dsn = os.getenv("sentry/dsn")
if sentry_dsn is not None:
    import sentry_sdk

    sentry_sdk.init(dsn=sentry_dsn)  # type: ignore

bot = TheCleanerApp(token=token)
bot.load_extension("clend.core.boot")

# hikari logger is already inited, so we can add ours
fh = logging.FileHandler("debug.log")
fh.setLevel(logging.DEBUG)
fh.setFormatter(
    logging.Formatter("%(levelname)-1.1s %(asctime)23.23s %(name)s: %(message)s")
)
logging.getLogger().addHandler(fh)


bot.run(asyncio_debug=True)
