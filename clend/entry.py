import sys
import typing
import logging

import hikari

from .bot import TheCleaner


logger = logging.getLogger(__name__)
MODULES_TO_RELOAD = (
    "clend",
    "cleaner_",
    "expirepy",
    "Levenshtein",
    "emoji",
    "janus",
    "typing_extensions",
    "pkg_resources",
)


class EntryExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, bot: TheCleaner) -> None:
        self.bot = bot
        self.extensions = [
            "clend.guild",
            "clend.http",
        ]
        self.listeners = [
            (hikari.StartedEvent, self.on_started),
            (hikari.StoppingEvent, self.on_stopping),
            (hikari.GuildMessageCreateEvent, self.on_message_create),
        ]

    def should_reload_module(self, module: str):
        if module == "clend" or module == "clend.bot" or module == __name__:
            return False
        elif module == "msgpack" or module.startswith("msgpack."):
            return False
        for mod_to_remove in MODULES_TO_RELOAD:
            if module.startswith(mod_to_remove):
                return True
        mod = sys.modules.get(module, None)
        if mod is not None:
            if (
                hasattr(mod, "__file__")
                and mod.__file__ is not None
                and "site-packages" in mod.__file__
            ):
                return None
        return False

    async def on_started(self, event: hikari.StartedEvent):
        self.load_dev()

    def load_dev(self):
        before = set(sys.modules.keys())
        self.bot.load_extension("clend.dev")
        after = set(sys.modules.keys())

        for module in before:
            if self.should_reload_module(module):
                logger.warning(f"static module is marked as reloadable: {module}")

        for module in after - before:
            if self.should_reload_module(module) is None:
                logger.warning(f"dynamic module that is not reloaded: {module}")

    async def on_stopping(self, event: hikari.StoppingEvent):
        self.bot.unload_extension("clend.dev")

    async def on_message_create(self, event: hikari.GuildMessageCreateEvent):
        if not self.bot.is_developer(event.author_id):
            return
        if event.content == "clean!full-reload":
            await self.handle_full_reload(event)

    async def handle_full_reload(self, event: hikari.GuildMessageCreateEvent):
        msg = await event.message.respond("Full reloading...")
        ext_errors = ext_unloaded = 0

        try:
            self.bot.unload_extension("clend.dev")
        except Exception as e:
            ext_errors += 1
            logger.error("Error unloading clend.dev", exc_info=e)
        else:
            ext_unloaded += 1

        for extension in tuple(self.bot.extensions):
            if extension != __name__:
                logger.warning(f"extension was not unloaded: {extension}")
                try:
                    self.bot.unload_extension(extension)
                except Exception as e:
                    ext_errors += 1
                    logger.error(
                        f"error while unloading extension: {extension}", exc_info=e
                    )
                else:
                    ext_unloaded += 1

        mod_removed = 0
        for module in tuple(sys.modules):
            if self.should_reload_module(module):
                del sys.modules[module]
                mod_removed += 1

        load_dev_error = False
        try:
            self.load_dev()
        except Exception as e:
            load_dev_error = True
            logger.error("Error while loading clend.dev", exc_info=e)

        await msg.edit(
            f"Unloaded {ext_unloaded} extensions ({ext_errors} errors)\n"
            f"Removed {mod_removed} modules from sys.modules.\n"
            f"Error while loading clend.dev: {'yes' if load_dev_error else 'no'}"
        )


extension = EntryExtension
