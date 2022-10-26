import hikari

from .._types import EntitlementsType


async def embedize_guild(
    guild: hikari.GatewayGuild | hikari.InviteGuild,
    bot: hikari.GatewayBot | None,
    entitlements: EntitlementsType | None,
    owner: hikari.User | None = None,
) -> hikari.Embed:
    embed = (
        hikari.Embed(color=0x34D399)
        .set_thumbnail(guild.make_icon_url())
        .add_field("Name", guild.name)
        .add_field("Created at", f"<t:{int(guild.created_at.timestamp())}>")
        .set_footer(str(guild.id))
    )

    if isinstance(guild, hikari.GatewayGuild):
        embed.add_field("Members", str(guild.member_count))
        if owner is not None and bot is not None:
            owner = bot.cache.get_user(guild.owner_id)
            if owner is None:
                owner = await guild.fetch_owner()

        if owner is None:
            embed.add_field("Owner ID", str(guild.owner_id))
        else:
            embed.add_field("Owner", f"{owner} ({owner.id})")

    elif owner is not None:
        embed.add_field("Owner", f"{owner} ({owner.id})")

    if guild.features:
        embed.add_field("Features", ", ".join(guild.features))

    if guild.vanity_url_code:
        vanity = guild.vanity_url_code
        embed.add_field("Vanity Invite", f"https://discord.gg/{vanity}")

    if entitlements is not None:
        if entitlements["suspended"]:
            embed.add_field(
                "Suspended", ":x: " + entitlements["suspended"], inline=True
            )
        if entitlements["plan"]:
            embed.add_field("Premium", ":white_check_mark:", inline=True)
        if entitlements["partnered"]:
            embed.add_field("Partnered", ":white_check_mark:", inline=True)

    return embed


def embedize_user(user: hikari.User) -> hikari.Embed:
    embed = (
        hikari.Embed(color=0x34D399)
        .set_thumbnail(user.make_avatar_url())
        .add_field("Name", str(user))
        .add_field("Created at", f"<t:{int(user.created_at.timestamp())}>")
        .set_footer(str(user.id))
    )
    if user.is_bot:
        embed.add_field("Bot", ":white_check_mark:")
    if user.flags and user.flags.name:
        embed.add_field("Flags", user.flags.name.replace("|", " "))
    return embed
