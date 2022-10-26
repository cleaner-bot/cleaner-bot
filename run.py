import logging
import os
from pathlib import Path

import hikari
from dotenv import load_dotenv

load_dotenv()


from cleaner.kernel.hypervisor import CleanerHypervisor  # noqa: E402

try:
    import uvloop

    uvloop.install()

except ImportError:
    pass


token = os.getenv("DISCORD_BOT_TOKEN")
if token is None:
    print("Token not found.")
    exit(1)


sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=sentry_dsn)


hypervisor = CleanerHypervisor(token=token)
pdata = Path() / "pdata"
if not pdata.exists():
    pdata.mkdir(parents=True)


@hypervisor.bot.listen()
async def on_started(event: hikari.StartedEvent) -> None:
    hypervisor.reload()


# hikari logger is already inited, so we can add ours
fh = logging.FileHandler(pdata / "debug.log")
fh.setLevel(logging.DEBUG)
fh.setFormatter(
    logging.Formatter("%(levelname)-1.1s %(asctime)23.23s %(name)s: %(message)s")
)
logging.getLogger().addHandler(fh)


hypervisor.bot.run(asyncio_debug=True)
