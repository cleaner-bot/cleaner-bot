import hikari
from cleaner_data.auto.phishing_embed_thumbnail import data as banned_thumbnails
from cleaner_data.domains import is_domain_blacklisted, is_domain_whitelisted
from cleaner_data.normalize import normalize
from cleaner_data.phishing_content import get_highest_phishing_match
from cleaner_data.url import get_urls, has_url
from Levenshtein import ratio  # type: ignore

from ...guild import CleanerGuild

banned_descriptions = {
    "and bigger discord discords e emoji enjoy fauorite file free from get in "
    "months more nitro of out stand steam upgrade uploads your",
}


def phishing_content(message: hikari.PartialMessage, guild: CleanerGuild) -> bool:
    if not message.content or not has_url(message.content):
        return False
    match = get_highest_phishing_match(message.content)
    return match > 0.9


def phishing_domain_blacklisted(
    message: hikari.PartialMessage, guild: CleanerGuild
) -> bool:
    if not message.content or not has_url(message.content):
        return False
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


def phishing_domain_heuristic(
    message: hikari.PartialMessage, guild: CleanerGuild
) -> bool:
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


def phishing_embed(message: hikari.PartialMessage, guild: CleanerGuild) -> bool:
    if not message.embeds:
        return False
    for embed in message.embeds:
        if not is_embed_legitimate(embed) and is_embed_suspicious(embed):
            return True
    return False


def is_embed_legitimate(embed: hikari.Embed) -> bool:
    if embed.url is None:
        return True
    hostname = embed.url.split("/")[2]
    return is_domain_whitelisted(hostname)


def is_embed_suspicious(embed: hikari.Embed) -> bool:
    if embed.description and normalize(embed.description) in banned_descriptions:
        return True

    if embed.thumbnail and embed.thumbnail.url in banned_thumbnails:
        return True

    return False
