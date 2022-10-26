from __future__ import annotations

import typing

import hikari

if typing.TYPE_CHECKING:
    from .._types import ConfigType


DANGEROUS_PERMISSIONS = (
    hikari.Permissions.KICK_MEMBERS
    | hikari.Permissions.BAN_MEMBERS
    | hikari.Permissions.ADMINISTRATOR
    | hikari.Permissions.MANAGE_CHANNELS
    | hikari.Permissions.MANAGE_GUILD
    | hikari.Permissions.MANAGE_MESSAGES
    | hikari.Permissions.MUTE_MEMBERS
    | hikari.Permissions.DEAFEN_MEMBERS
    | hikari.Permissions.MOVE_MEMBERS
    | hikari.Permissions.MANAGE_NICKNAMES
    | hikari.Permissions.MANAGE_ROLES
    | hikari.Permissions.MANAGE_WEBHOOKS
    | hikari.Permissions.MANAGE_EMOJIS_AND_STICKERS
    # | hikari.Permissions.MANAGE_EVENTS
    | hikari.Permissions.MANAGE_THREADS
    | hikari.Permissions.MODERATE_MEMBERS
)


def permissions_for(
    member: hikari.Member, channel: hikari.GuildChannel
) -> hikari.Permissions:
    permissions = hikari.Permissions.NONE
    for role in member.get_roles():
        permissions |= role.permissions

    if permissions & hikari.Permissions.ADMINISTRATOR:
        return hikari.Permissions.ADMINISTRATOR

    overwrite_everyone = channel.permission_overwrites.get(channel.guild_id)
    if overwrite_everyone:
        permissions &= ~overwrite_everyone.deny
        permissions |= overwrite_everyone.allow

    allow = hikari.Permissions.NONE
    deny = hikari.Permissions.NONE
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
) -> hikari.Permissions:
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


def is_moderator(
    member: hikari.Member | None, guild: hikari.Guild | None, config: ConfigType
) -> bool:
    if (
        member is None  # webhook
        or member.is_bot
        or (guild is not None and guild.owner_id == member.id)
        or bool(set(config["general_modroles"]) & set(map(str, member.role_ids)))
    ):
        return True

    for role in member.get_roles():
        if role.permissions & hikari.Permissions.ADMINISTRATOR:
            return True
        elif role.permissions & hikari.Permissions.MANAGE_GUILD:
            return True

    return False
