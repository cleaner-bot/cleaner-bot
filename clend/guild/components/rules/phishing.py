import hikari
from cleaner_data.auto.phishing_embed_thumbnail import data as banned_thumbnails
from cleaner_data.domains import is_domain_blacklisted, is_domain_whitelisted
from cleaner_data.phishing_content import get_highest_phishing_match
from cleaner_data.url import get_urls, has_url
from Levenshtein import ratio  # type: ignore


def phishing_content(message: hikari.PartialMessage, guild):
    if not message.content or not has_url(message.content):
        return
    match = get_highest_phishing_match(message.content)
    return match > 0.9


def phishing_domain_blacklisted(message: hikari.PartialMessage, guild):
    if not message.content or not has_url(message.content):
        return
    for url in get_urls(message.content):
        hostname = url.split("/")[2]
        if is_domain_blacklisted(hostname):
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


def phishing_domain_heuristic(message: hikari.PartialMessage, guild):
    if not message.content or not has_url(message.content):
        return False
    for url in get_urls(message.content):
        hostname = url.split("/")[2]
        if is_domain_whitelisted(hostname):
            continue
        for part in hostname.replace("-", ".").split("."):
            for banned in suspicious_parts:
                if 1 > ratio(part, banned) >= 0.7:
                    return True
                elif part == "nitro":
                    return True

    return False


def phishing_embed(message: hikari.PartialMessage, guild):
    if not message.embeds:
        return
    for embed in message.embeds:
        url = embed.url
        if url is None:
            continue
        hostname = url.split("/")[2]
        if (
            not is_domain_whitelisted(hostname)
            and embed.thumbnail
            and embed.thumbnail.url in banned_thumbnails
        ):
            return True
    return False
