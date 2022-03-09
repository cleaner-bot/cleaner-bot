import hikari


def on_member_create(event: hikari.MemberCreateEvent, guild):
    guild.member_joins.change()


def on_member_delete(event: hikari.MemberDeleteEvent, guild):
    guild.member_joins.change(-1)


listeners = [
    (hikari.MemberCreateEvent, on_member_create),
    (hikari.MemberDeleteEvent, on_member_delete),
]
