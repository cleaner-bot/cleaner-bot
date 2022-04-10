import hikari

from ..guild import CleanerGuild
from ..helper import is_moderator, is_exception, change_ratelimit
from ...shared.custom_events import FastTimerEvent


slowmode = [round(x ** 1.3 / 15) for x in range(60)]


def on_message_create(event: hikari.GuildMessageCreateEvent, guild: CleanerGuild):
    config = guild.get_config()
    if (
        event.member is None
        or is_moderator(guild, event.member)
        or config is None
        or not config.slowmode_enabled
    ):
        return
    channel = event.get_channel()
    if channel is None:
        return

    counter = guild.pending_message_count.get(event.channel_id, 0)
    guild.pending_message_count[event.channel_id] = counter + 1


def on_fast_timer(event: FastTimerEvent, cguild: CleanerGuild):
    config = cguild.get_config()
    if (
        config is None
        or not config.slowmode_enabled
        or not cguild.pending_message_count
    ):
        return

    guild = event.app.cache.get_guild(cguild.id)
    if guild is None:
        return

    for channel_id, count in cguild.pending_message_count.items():
        counts = cguild.message_count.get(channel_id, None)
        if counts is None:
            counts = cguild.message_count[channel_id] = [0, 0, 0, 0, 0, 0]
        counts.append(count)
        if len(counts) > 6:
            counts.pop(0)
        cguild.pending_message_count[channel_id] = 0

    actions = []

    for channel_id, counts in cguild.message_count.items():
        spike = counts[-1]
        avg = round(sum(counts) / len(counts))

        default = 0 if is_exception(config, channel_id) else 1
        current = cguild.current_slowmode.get(channel_id, default)

        if default == 0:  # exception channel, decrease slowmode
            spike //= 5
            avg //= 5

        spike_rt = default + (10 if spike >= len(slowmode) else slowmode[spike])
        avg_rt = default + (10 if avg >= len(slowmode) else slowmode[avg])

        if spike_rt > current + 1 or avg_rt != current:
            channel = guild.get_channel(channel_id)
            if channel is not None and isinstance(channel, hikari.TextableGuildChannel):
                recommended = spike_rt if spike_rt > current + 1 else avg_rt
                actions.append(change_ratelimit(channel, recommended))

    return actions


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
    (FastTimerEvent, on_fast_timer),
]
