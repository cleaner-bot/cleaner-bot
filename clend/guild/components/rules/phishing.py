import hikari
from Levenshtein import ratio  # type: ignore

from cleaner_data.domains import is_whitelisted, is_blacklisted
from cleaner_data.phishing_content import get_highest_match
from cleaner_data.url import get_urls, has_url


def phishing_content(message: hikari.Message, guild):
    if not message.content or not has_url(message.content):
        return
    match = get_highest_match(message.content)
    return match > 0.9


def phishing_domain_blacklisted(message: hikari.Message, guild):
    if not message.content or not has_url(message.content):
        return
    for url in get_urls(message.content):
        hostname = url.split("/")[2]
        if is_blacklisted(hostname):
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


def phishing_domain_heuristic(message: hikari.Message, guild):
    if not message.content or not has_url(message.content):
        return False
    for url in get_urls(message.content):
        hostname = url.split("/")[2]
        if is_whitelisted(hostname):
            continue
        for part in hostname.replace("-", ".").split("."):
            for banned in suspicious_parts:
                if 1 > ratio(part, banned) >= 0.7:
                    return True
                elif part == "nitro":
                    return True

    return False


banned_thumbnails = {
    "https://discord.com/assets/652f40427e1f5186ad54836074898279.png",
    "https://nebanueban.hb.bizmrg.com/qwqwe12qw.webp",
}


def phishing_embed(message: hikari.Message, guild):
    for embed in message.embeds:
        url = embed.url
        if url is None:
            continue
        hostname = url.split("/")[2]
        if (
            not is_whitelisted(hostname)
            and embed.thumbnail
            and embed.thumbnail.url in banned_thumbnails
        ):
            return True
    return False
