import hikari
from cleaner_conf.guild import GuildConfig
from cleaner_i18n.translate import Message

from ..shared.channel_perms import permissions_for
from ..shared.dangerous import DANGEROUS_PERMISSIONS
from ..shared.event import (
    IActionAnnouncement,
    IActionChallenge,
    IActionChannelRatelimit,
    IActionDelete,
    IActionNickname,
)
from .guild import CleanerGuild

PERM_BAN = hikari.Permissions.ADMINISTRATOR | hikari.Permissions.BAN_MEMBERS
PERM_KICK = hikari.Permissions.ADMINISTRATOR | hikari.Permissions.KICK_MEMBERS
PERM_TIMEOUT = hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MODERATE_MEMBERS
PERM_NICK = hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_NICKNAMES
PERM_MOD = hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD
PERM_SEND = hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL


def action_challenge(
    cguild: CleanerGuild, member: hikari.Member, block: bool = False, **kwargs
) -> IActionChallenge:
    guild = member.get_guild()
    data = cguild.get_data()
    if guild is None or member.id == guild.owner_id:
        return IActionChallenge(
            guild_id=member.guild_id,
            user=member.user,
            block=block,
            can_ban=False,
            can_kick=False,
            can_timeout=False,
            can_role=False,
            take_role=False,
            role_id=0,
            **kwargs
        )

    role: hikari.Role | None = None

    me = guild.get_my_member()
    my_perms = hikari.Permissions.NONE
    if me is not None:
        for role in me.get_roles():
            my_perms |= role.permissions

    his_perms = hikari.Permissions.NONE
    for role in member.get_roles():
        his_perms |= role.permissions

    above_role = False
    toprole_me = None
    if me is not None:
        toprole_me = me.get_top_role()
        toprole_member = member.get_top_role()
        if toprole_me is not None and toprole_member is not None:
            above_role = toprole_me.position > toprole_member.position

    role = None
    if data is not None and data.config.challenge_interactive_enabled:
        role_id = int(data.config.challenge_interactive_role)
        role = guild.get_role(role_id)

    can_timeout = (
        (data is None or data.config.challenge_timeout_enabled)
        and his_perms & hikari.Permissions.ADMINISTRATOR == 0
        and above_role
        and my_perms & PERM_TIMEOUT > 0
    )
    can_role = (
        role is not None
        and me is not None
        and toprole_me is not None
        and toprole_me.position > role.position
        and (
            data is None
            or (role.id in member.role_ids)
            != data.config.challenge_interactive_take_role
        )
        and role.permissions & DANGEROUS_PERMISSIONS == 0
    )
    action = IActionChallenge(
        guild_id=guild.id,
        user=member.user,
        block=block,
        can_ban=above_role and my_perms & PERM_BAN > 0,
        can_kick=above_role and my_perms & PERM_KICK > 0,
        can_timeout=can_timeout,
        can_role=can_role,
        take_role=True if data is None else data.config.challenge_interactive_take_role,
        role_id=role.id if role else 0,
        **kwargs
    )

    return action


def action_nickname(
    member: hikari.Member, nickname: str | None, **kwargs
) -> IActionNickname:
    guild = member.get_guild()
    if guild is None or member.id == guild.owner_id:
        return IActionNickname(
            guild_id=member.guild_id,
            user=member.user,
            nickname=nickname,
            can_change=False,
            can_kick=False,
            can_ban=False,
            **kwargs
        )

    me = guild.get_my_member()
    my_perms = hikari.Permissions.NONE
    if me is not None:
        for role in me.get_roles():
            my_perms |= role.permissions

    above_role = False
    if me is not None:
        toprole_me = me.get_top_role()
        toprole_member = member.get_top_role()
        if toprole_me is not None and toprole_member is not None:
            above_role = toprole_me.position > toprole_member.position

    return IActionNickname(
        guild_id=guild.id,
        user=member.user,
        nickname=nickname,
        can_change=above_role and my_perms & PERM_NICK > 0,
        can_kick=above_role and my_perms & PERM_KICK > 0,
        can_ban=above_role and my_perms & PERM_BAN > 0,
        **kwargs
    )


def action_delete(
    member: hikari.Member, message: hikari.PartialMessage, **kwargs
) -> IActionDelete:
    guild = member.get_guild()
    if guild is None:
        return IActionDelete(
            guild_id=member.guild_id,
            user=member.user,
            channel_id=message.channel_id,
            message_id=message.id,
            can_delete=False,
            message=message,
            **kwargs
        )

    me = guild.get_my_member()
    channel = guild.get_channel(message.channel_id)

    if me is None or channel is None:
        return IActionDelete(
            guild_id=member.guild_id,
            user=member.user,
            channel_id=message.channel_id,
            message_id=message.id,
            can_delete=False,
            message=message,
            **kwargs
        )

    my_perms = hikari.Permissions.NONE
    for role in me.get_roles():
        my_perms |= role.permissions

    perms = permissions_for(me, channel)
    can_delete = (
        perms & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_MESSAGES)
        > 0
    )
    if can_delete:
        can_delete = (
            perms & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.VIEW_CHANNEL)
            > 0
        )

    return IActionDelete(
        guild_id=guild.id,
        user=member.user,
        channel_id=channel.id,
        message_id=message.id,
        can_delete=can_delete,
        message=message,
        **kwargs
    )


def announcement(
    channel: hikari.TextableGuildChannel,
    announcement: Message,
    delete_after: float,
) -> IActionAnnouncement:
    guild = channel.get_guild()

    if guild is None:
        return IActionAnnouncement(
            guild_id=channel.guild_id,
            channel_id=channel.id,
            can_send=False,
            announcement=announcement,
            delete_after=delete_after,
        )

    me = guild.get_my_member()

    if me is None:
        return IActionAnnouncement(
            guild_id=channel.guild_id,
            channel_id=channel.id,
            can_send=False,
            announcement=announcement,
            delete_after=delete_after,
        )

    perms = permissions_for(me, channel)

    can_send = perms & PERM_SEND == PERM_SEND
    if perms & hikari.Permissions.ADMINISTRATOR:
        can_send = True

    return IActionAnnouncement(
        guild_id=channel.guild_id,
        channel_id=channel.id,
        can_send=can_send,
        announcement=announcement,
        delete_after=delete_after,
    )


def change_ratelimit(
    channel: hikari.TextableGuildChannel, ratelimit: int
) -> IActionChannelRatelimit:
    guild = channel.get_guild()

    if guild is None:
        return IActionChannelRatelimit(
            guild_id=channel.guild_id,
            channel_id=channel.id,
            ratelimit=ratelimit,
            can_modify=False,
        )

    me = guild.get_my_member()

    if me is None:
        return IActionChannelRatelimit(
            guild_id=channel.guild_id,
            channel_id=channel.id,
            ratelimit=ratelimit,
            can_modify=False,
        )

    perms = permissions_for(me, channel)

    can_modify = (
        perms & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_CHANNELS)
        > 0
    )

    return IActionChannelRatelimit(
        guild_id=channel.guild_id,
        channel_id=channel.id,
        ratelimit=ratelimit,
        can_modify=can_modify,
    )


def is_moderator(cguild: CleanerGuild, member: hikari.Member) -> bool:
    guild = member.get_guild()
    if member.is_bot or (guild is not None and member.id == guild.owner_id):
        return True
    data = cguild.get_data()
    if data is not None:
        modroles = set(map(int, data.config.general_modroles))
        for role in member.get_roles():
            if role.id in modroles:
                return True
            elif role.permissions & PERM_MOD:
                return True
    return False


def is_exception(config_or_guild: CleanerGuild | GuildConfig, channel_id: int):
    if isinstance(config_or_guild, CleanerGuild):
        data = config_or_guild.get_data()
        if data is None:
            return False
        config = data.config
    else:
        config = config_or_guild

    return str(channel_id) in config.slowmode_exceptions
