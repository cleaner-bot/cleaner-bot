import hikari

from cleaner_data.url import has_url

from ..bot import TheCleaner
from ..shared.event import IActionDelete


def is_likely_phishing(ev: IActionDelete) -> bool:
    return (
        ev.message is not None
        and ev.message.content is not None
        and has_url(ev.message.content)
        and (
            "phishing" in ev.info.get("rule", "")
            or "traffic.exact" == ev.info.get("rule", "")
            or "ping.broad" == ev.info.get("rule", "")
        )
    )


async def report_phishing(ev: IActionDelete, bot: TheCleaner):
    if ev.message is None:
        return

    channel_id = 963043098999533619

    rule = ev.info.get("rule", "???")
    embed = hikari.Embed(description=ev.message.content, color=0xE74C3C)

    embed.set_author(name=f"Suspicious message | {rule}")

    user = bot.bot.cache.get_user(ev.user_id)
    if user is None:
        embed.set_footer(text=str(ev.user_id))
    else:
        embed.set_footer(
            text=f"{user} ({ev.user_id})", icon=user.make_avatar_url(ext="webp", size=64)
        )

    embed.add_field("Channel", f"<#{ev.channel_id}>")

    guild = bot.bot.cache.get_guild(ev.guild_id)
    if guild is None:
        embed.add_field("Guild", str(ev.guild_id))
    else:
        embed.add_field("Guild", f"{guild.name} ({ev.guild_id})")

    await bot.bot.rest.create_message(channel_id, embed=embed)
