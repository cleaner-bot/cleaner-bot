from expirepy import ExpiringCounter
import hikari

from ..guild import CleanerGuild
from ..helper import is_moderator, change_ratelimit


# all = [round(x ** 1.5 / 100) for x in range(98)]
# [all.index(x) for x in range(1, 11)]
slowmode_steps = [14, 29, 40, 50, 59, 68, 76, 83, 90, 97]
slowmode = []
_ = 0
for __ in range(98):
    if __ in slowmode_steps:
        _ += 1
    slowmode.append(_)


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

    counter = guild.message_count.get(event.channel_id, None)
    if counter is None:
        counter = guild.message_count[event.channel_id] = ExpiringCounter(expires=60)

    counter.increase()
    count = counter.value()

    default = 0 if event.channel_id in config.slowmode_exceptions else 1
    current = guild.current_slowmode.get(event.channel_id, default)

    if default == 0:
        count /= 5
    recommended = 10 if count >= len(slowmode) else slowmode[count]
    if default == 1 and not recommended:
        recommended = 1

    if recommended != current:
        guild.current_slowmode[event.channel_id] = recommended
        return [
            change_ratelimit(channel, recommended),
        ]


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
]
