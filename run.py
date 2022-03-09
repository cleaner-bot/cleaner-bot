import asyncio

from clend.bot import TheCleaner


try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


bot = TheCleaner(
    token="OTMyMjY1MzMzOTE2NTkwMTYw.YeQdwA.PYpM9YIDLZicDJVktLquIzy-goI",
)
bot.load_extension("clend.dev")
bot.run()
