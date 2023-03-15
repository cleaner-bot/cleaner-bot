import hikari

from .._types import KernelType
from ..helpers.regex import DISCORD_INVITE
from ..helpers.url import get_urls


def advertisement_discord(kernel: KernelType, message: hikari.PartialMessage) -> bool:
    if not message.content:
        return False

    return DISCORD_INVITE.search(message.content) is not None


def advertisement_unsafediscord(
    kernel: KernelType, message: hikari.PartialMessage
) -> bool:
    if not message.content:
        return False

    invites = DISCORD_INVITE.findall(message.content)
    for _, invite in invites:
        if invite in kernel.data["discord_invite_blacklist"]:
            return True

    return False


def advertisement_unsafelink(
    kernel: KernelType, message: hikari.PartialMessage
) -> bool:
    if not message.content:
        return False

    # /invite/i=

    for url in get_urls(message.content):
        if "/invite/i=" in url:
            return True

    return False
