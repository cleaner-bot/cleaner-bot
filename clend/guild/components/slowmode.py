import hikari

from cleaner.clend.shared.custom_events import FastTimerEvent

from ..guild import CleanerGuild
from ..helper import is_moderator, is_exception, change_ratelimit


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

    counter.increase()


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
        current = cguild.message_count.get(channel_id, None)
        if current is None:
            current = cguild.message_count[channel_id] = [0, 0, 0, 0, 0, 0]
        current.append(count)
        if len(current) > 6:
            current.pop(0)
        cguild.pending_message_count[channel_id] = 0

    actions = []

    for channel_id, counts in cguild.message_count:
        spike = counts[-1]
        avg = sum(counts) / len(counts)

        default = 0 if is_exception(config, channel_id) else 1
        current = cguild.current_slowmode.get(channel_id, default)

        spike_rt = 10 if spike >= len(slowmode) else slowmode[spike]
        avg_rt = 10 if avg >= len(slowmode) else slowmode[avg]

        if spike_rt > current + 1 or avg_rt != current:
            channel = guild.get_channel(channel_id)
            if channel is not None and isinstance(channel, hikari.TextableGuildChannel):
                recommended = spike_rt if spike_rt > current + 1 else avg_rt
                actions.append(change_ratelimit(channel, recommended))

    if default == 0:
        count /= 5
    recommended = 10 if count >= len(slowmode) else slowmode[count]
    if default == 1 and not recommended:
        recommended = 1

    if recommended != current:
        guild.current_slowmode[event.channel_id] = recommended
        return (change_ratelimit(channel, recommended),)

    return actions


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
    (FastTimerEvent, on_fast_timer),
]
