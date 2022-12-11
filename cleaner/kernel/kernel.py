from __future__ import annotations

import importlib
import logging
import typing

from coredis import Redis
from hikari import GatewayBot, Locale

from ._types import HypervisorType

logger = logging.getLogger(__name__)
DEVELOPERS: typing.Final = {
    # 633993042755452932,  # leo
    922118393178517545,  # sora
    918875640046964797,  # shiro
    647558454491480064,  # [blank]
    644897993216098305,  # stressed by a mountain of books
}
EXTENSIONS: typing.Final = (
    "cleaner.userland.data:DataService",
    "cleaner.userland.consumers.basic:BasicConsumerService",
    "cleaner.userland.consumers.interactions:InteractionsConsumerService",
    "cleaner.userland.consumers.rpc:RPCConsumerService",
    "cleaner.userland.verification.core:VerificationService",
    "cleaner.userland.verification.discord:DiscordVerificationService",
    "cleaner.userland.verification.external:ExternalVerificationService",
    "cleaner.userland.antiraid:AntiRaidService",
    "cleaner.userland.antispam:AntispamService",
    "cleaner.userland.automod:AutoModService",
    "cleaner.userland.slowmode:SlowmodeService",
    "cleaner.userland.http:HTTPService",
    "cleaner.userland.joinguard:JoinGuardService",
    "cleaner.userland.linkfilter:LinkFilterService",
    "cleaner.userland.name:NameService",
    "cleaner.userland.super_verification:SuperVerificationService",
    "cleaner.userland.bansync:BanSyncService",
    "cleaner.userland.dehoist:DehoistService",
    "cleaner.userland.log:LogService",
    "cleaner.userland.radar:RadarService",
    "cleaner.userland.integration:IntegrationService",
    "cleaner.userland.suspension:SuspensionService",
    "cleaner.userland.commands:CommandsService",
    "cleaner.userland.members:MembersService",
    "cleaner.userland.auth:AuthService",
    # "cleaner.userland.mfa:MFAService",
    "cleaner.userland.dashboard:DashboardService",
    "cleaner.userland.report:ReportService",
    "cleaner.userland.statistics:StatisticsService",
    "cleaner.userland.dev:DeveloperService",
)


class CleanerKernel:
    bot: GatewayBot
    database: Redis[bytes]
    extensions: dict[str, typing.Any]

    rpc: dict[str, typing.Any]
    bindings: dict[str, typing.Any]
    longterm: dict[str, typing.Any]
    interactions: dict[str, dict[str, typing.Any]]
    data: dict[str, typing.Any]

    def __init__(self, hypervisor: HypervisorType) -> None:
        self.bot = hypervisor.bot
        self.database = hypervisor.database

        self.extensions = {}

        self.rpc = {}
        self.bindings = {}
        self.longterm = {}
        self.interactions = {"commands": {}, "components": {}, "modals": {}}
        self.data = {}

        for extension in EXTENSIONS:
            self.load_safe_extension(extension)

    def load_safe_extension(self, module: str) -> bool:
        try:
            self.load_extension(module)
        except Exception as e:
            logger.exception(f"failed to load extension: {module}", exc_info=e)
            return False
        return True

    def load_extension(self, module: str) -> None:
        module_name, class_name = module.split(":")
        if module_name in self.extensions:
            raise RuntimeError(f"extension already loaded: {module!r}")
        mod = importlib.import_module(module_name)
        self.extensions[module] = getattr(mod, class_name)(self)

    def unload_extension(self, module: str) -> None:
        ext = self.extensions[module]
        if hasattr(ext, "on_unload"):
            ext.on_unload()
        del self.extensions[module]

    @staticmethod
    def is_developer(user_id: int) -> bool:
        return user_id in DEVELOPERS

    def translate(self, language: str, key: str, /, **kwargs: str) -> str:
        localization = typing.cast(
            dict[str, dict[str, str]], self.data.get("localization")
        )
        if localization is None or key.startswith("_"):
            return key

        locale = localization.get(language, None)
        if locale is None:
            language = Locale.EN_US
            locale = localization[language]

        string = locale.get(key)
        if string is None:
            if language == Locale.EN_US:
                return key
            locale = localization[Locale.EN_US]
            string = locale.get(key)
            if string is None:
                return key

        return string.format(**kwargs)
