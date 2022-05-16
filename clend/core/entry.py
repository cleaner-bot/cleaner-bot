"""
This is the 2nd stage loader, responsible for loading the other extensions.
"""
import logging
import typing

import hikari

from ..app import TheCleanerApp

logger = logging.getLogger(__name__)
EXTENSIONS = [
    "clend.core.dev",
    "clend.timer",
    "clend.conf",
    "clend.http",
    "clend.guild",
    "clend.challenge",
    "clend.verification",
    "clend.sync",
    "clend.slash",
    "clend.report",
    "clend.analytics",
    "clend.metrics",
    "clend.guildlog",
    "clend.downdoom",
    "clend.traffic",
    "clend.integrations",
]


class EntryExtension:
    listeners: list[tuple[typing.Type[hikari.Event], typing.Callable]]

    def __init__(self, app: TheCleanerApp) -> None:
        self.app = app
        self.listeners = []

    def on_load(self):
        try:
            self.app.load_store()
        except Exception as e:
            logger.exception("An error occured while loading store", exc_info=e)

        for ext in EXTENSIONS:
            if ext in self.app.extensions:
                logger.warning(f"loading already loaded extension: {ext}")
            else:
                try:
                    self.app.load_extension(ext)
                except Exception as e:
                    logger.exception(
                        f"An error occured while loading extension: {ext}", exc_info=e
                    )

    def on_unload(self):
        for ext in EXTENSIONS:
            if ext in self.app.extensions:
                try:
                    self.app.unload_extension(ext)
                except Exception as e:
                    logger.exception(
                        f"An error occured while unloading extension: {ext}", exc_info=e
                    )
            else:
                logger.warning(f"extension was never loaded: {ext}")


extension = EntryExtension
