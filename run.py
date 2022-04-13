import asyncio
from pathlib import Path
import logging
import os

from dotenv import load_dotenv

load_dotenv(Path("~/.cleaner/secrets").expanduser())
load_dotenv(Path("~/.cleaner/env").expanduser())
load_dotenv(Path("~/.cleaner/env_bot").expanduser())

from clend.bot import TheCleaner  # noqa: E402
from pcex import inject  # noqa: E402


try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


token = os.getenv("SECRET_BOT_TOKEN")
if token is None:
    print("Token not found.")
    exit(1)


sentry_dsn = os.getenv("SECRET_SENTRY_DSN")
if sentry_dsn is not None:
    import sentry_sdk

    sentry_sdk.init(dsn=sentry_dsn)

bot = TheCleaner(token=token)
inject(bot.bot)
bot.load_extension("clend.entry")

# hikari logger is already inited, so we can add ours
fh = logging.FileHandler("debug.log")
fh.setLevel(logging.DEBUG)
fh.setFormatter(
    logging.Formatter("%(levelname)-1.1s %(asctime)23.23s %(name)s: %(message)s")
)
logging.getLogger().addHandler(fh)

bot.run(asyncio_debug=True)
