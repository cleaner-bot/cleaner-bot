"""
This is the first stage entry loader.
Any changes to this loader need a full bot reload.
"""

import sys
import typing
import logging

import hikari

from ..app import TheCleanerApp


logger = logging.getLogger(__name__)
ENTRY_EXTENSION = "clend.core.entry"
MODULES_TO_RELOAD = (
    "clend",
    "expirepy",
    "Levenshtein",
    "emoji",
    "janus",
    "pkg_resources",
    "pydantic",
    "downdoom",
)
MODULES_TO_NOT_RELOAD = (
    "msgpack",
    "coredis",
    "typing_extensions",
)


class EntryExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
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
        elif module.startswith("cleaner_"):
            return True

        for mod_to_not_remove in MODULES_TO_NOT_RELOAD:
            if module == mod_to_not_remove or module.startswith(
                mod_to_not_remove + "."
            ):
                return False

        for mod_to_remove in MODULES_TO_RELOAD:
            if module == mod_to_remove or module.startswith(mod_to_remove + "."):
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
        self.app.load_extension("clend.entry.entry")
        after = set(sys.modules.keys())

        for module in before:
            if self.should_reload_module(module):
                logger.warning(f"static module is marked as reloadable: {module}")

        for module in after - before:
            if self.should_reload_module(module) is None:
                logger.warning(f"dynamic module that is not reloaded: {module}")

    async def on_stopping(self, event: hikari.StoppingEvent):
        self.app.unload_extension(ENTRY_EXTENSION)

    async def on_message_create(self, event: hikari.GuildMessageCreateEvent):
        if not self.app.is_developer(event.author_id):
            return
        if event.content == "clean!full-reload":
            await self.handle_full_reload(event)

    async def handle_full_reload(self, event: hikari.GuildMessageCreateEvent):
        msg = await event.message.respond("Full reloading...")
        ext_errors = ext_unloaded = 0

        try:
            self.app.unload_extension(ENTRY_EXTENSION)
        except Exception as e:
            ext_errors += 1
            logger.error(f"Error unloading {ENTRY_EXTENSION}", exc_info=e)
        else:
            ext_unloaded += 1

        for extension in tuple(self.app.extensions):
            if extension != __name__:
                logger.warning(f"extension was not unloaded: {extension}")
                try:
                    self.app.unload_extension(extension)
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
            logger.error(f"Error while loading {ENTRY_EXTENSION}", exc_info=e)

        await msg.edit(
            f"Unloaded {ext_unloaded} extensions ({ext_errors} errors)\n"
            f"Removed {mod_removed} modules from sys.modules.\n"
            f"Error while loading {ENTRY_EXTENSION}: {load_dev_error}"
        )


extension = EntryExtension
