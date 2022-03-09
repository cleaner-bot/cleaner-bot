import hikari


def permissions_for(member: hikari.Member, channel: hikari.GuildChannel):
    permissions = 0
    for role in member.get_roles():
        permissions |= role.permissions

    if permissions & hikari.Permissions.ADMINISTRATOR:
        return hikari.Permissions.ADMINISTRATOR

    overwrite_everyone = channel.permission_overwrites.get(channel.guild_id)
    if overwrite_everyone:
        permissions &= ~overwrite_everyone.deny
        permissions |= overwrite_everyone.allow

    allow = 0
    deny = 0
    for role_id in member.role_ids:
        overwrite_role = channel.permission_overwrites.get(role_id)
        if overwrite_role:
            allow |= overwrite_role.allow
            deny |= overwrite_role.deny

    permissions &= ~deny
    permissions |= allow

    overwrite_member = channel.permission_overwrites.get(member.id)
    if overwrite_member:
        permissions &= ~overwrite_member.deny
        permissions |= overwrite_member.allow

    return permissions


def permissions_for_role(
    role: hikari.Role, guild: hikari.Guild, channel: hikari.GuildChannel
):
    permissions = role.permissions
    if (everyone_role := guild.get_role(guild.id)) is not None:
        permissions |= everyone_role.permissions
    if permissions & hikari.Permissions.ADMINISTRATOR:
        return hikari.Permissions.ADMINISTRATOR

    overwrite_everyone = channel.permission_overwrites.get(channel.guild_id)
    if overwrite_everyone:
        permissions &= ~overwrite_everyone.deny
        permissions |= overwrite_everyone.allow

    overwrite_role = channel.permission_overwrites.get(role.id)
    if overwrite_role:
        permissions &= ~overwrite_role.deny
        permissions |= overwrite_role.allow

    return permissions
