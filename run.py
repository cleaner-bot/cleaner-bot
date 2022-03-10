import asyncio
import os

import dotenv
dotenv.load_dotenv()

from clend.bot import TheCleaner


try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


bot = TheCleaner(token=os.getenv("SECRET_BOT_TOKEN"))
bot.load_extension("clend.dev")
bot.run()
