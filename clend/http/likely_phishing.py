import hikari
from cleaner_data.url import has_url

from ..app import TheCleanerApp
from ..shared.event import IActionDelete


def is_likely_phishing(ev: IActionDelete) -> bool:
    return (
        ev.message is not None
        and isinstance(ev.message.content, str)
        and has_url(ev.message.content)
        and (
            "phishing" in ev.info.get("rule", "")
            or "traffic.exact" == ev.info.get("rule", "")
            or "ping.broad" == ev.info.get("rule", "")
        )
    )


async def report_phishing(ev: IActionDelete, app: TheCleanerApp) -> None:
    if ev.message is None:
        return

    channel_id = 963043098999533619

    rule = ev.info.get("rule", "???")
    embed = hikari.Embed(description=ev.message.content, color=0xE74C3C)

    embed.set_author(name=f"Suspicious message | {rule}")

    embed.set_footer(
        text=f"{ev.user} ({ev.user.id})",
        icon=ev.user.make_avatar_url(ext="webp", size=64),
    )

    if ev.message.embeds:
        evil_embed = ev.message.embeds[0]
        if evil_embed.title:
            embed.add_field("Title", evil_embed.title)
        if evil_embed.description:
            embed.add_field("Description", evil_embed.description)
        if evil_embed.thumbnail:
            embed.add_field("Thumbnail", evil_embed.thumbnail.url)

    embed.add_field("Channel", f"<#{ev.channel_id}>")

    guild = app.bot.cache.get_guild(ev.guild_id)
    if guild is None:
        embed.add_field("Guild", str(ev.guild_id))
    else:
        embed.add_field("Guild", f"{guild.name} ({ev.guild_id})")

    await app.bot.rest.create_message(channel_id, embed=embed)
