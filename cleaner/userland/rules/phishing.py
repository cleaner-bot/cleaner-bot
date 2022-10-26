import hikari
from Levenshtein import ratio  # type: ignore

from .._types import KernelType
from ..helpers.tokenizer import tokenize
from ..helpers.url import domain_in_list, get_urls, has_url, remove_urls


def phishing_content(kernel: KernelType, message: hikari.PartialMessage) -> bool:
    if not message.content or not has_url(message.content):
        return False
    content = " ".join(
        sorted(
            set(x for x in tokenize(remove_urls(message.content.lower())) if x.strip())
        )
    )
    for known_content in kernel.data["phishing_content"]:
        match = ratio(content, known_content)
        if match > 0.9:
            return True
    return False


def phishing_domain_blacklisted(
    kernel: KernelType, message: hikari.PartialMessage
) -> bool:
    if not message.content or not has_url(message.content):
        return False
    for url in get_urls(message.content):
        hostname = url.split("/")[2]
        if domain_in_list(hostname, kernel.data["phishing_domain_blacklist"]):
            return True
    return False


suspicious_parts = (
    "steamcommunity",
    "steampowered",
    "discord",
    "discordapp",
    "nitro",
    "gift",
)


def phishing_domain_heuristic(
    kernel: KernelType, message: hikari.PartialMessage
) -> bool:
    if not message.content or not has_url(message.content):
        return False
    for url in get_urls(message.content):
        hostname = url.split("/")[2]
        if domain_in_list(hostname, kernel.data["phishing_domain_whitelist"]):
            continue
        for part in hostname.replace("-", ".").split("."):
            for banned in suspicious_parts:
                if 1 > ratio(part, banned) >= 0.7:
                    return True
                elif part == "nitro":
                    return True

    return False


def phishing_embed(kernel: KernelType, message: hikari.PartialMessage) -> bool:
    if not message.embeds:
        return False
    banned_thumbnails = kernel.data["phishing_embed_thumbnails"]
    for embed in message.embeds:
        url = embed.url
        if url is None:
            continue
        hostname = url.split("/")[2]
        if (
            not domain_in_list(hostname, kernel.data["phishing_domain_whitelist"])
            and embed.thumbnail
            and embed.thumbnail.url in banned_thumbnails
        ):
            return True
    return False
