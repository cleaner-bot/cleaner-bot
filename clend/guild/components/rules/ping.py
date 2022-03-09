import hikari


def ping_users_many(message: hikari.Message, guild) -> bool:
    if message.mentions.user_ids is hikari.UNDEFINED:
        return False
    pings = len(message.mentions.user_ids)
    return pings >= 15


def ping_users_few(message: hikari.Message, guild) -> bool:
    if message.mentions.user_ids is hikari.UNDEFINED:
        return False
    pings = len(message.mentions.user_ids)
    return pings >= 5


def ping_roles(message: hikari.Message, guild) -> bool:
    if message.mentions.role_ids is hikari.UNDEFINED:
        return False
    pings = len(message.mentions.role_ids)
    return pings >= 5


def ping_broad(message: hikari.Message, guild) -> bool:
    if not message.content or message.mentions.everyone:
        return False
    return "@everyone" in message.content or "@here" in message.content


def ping_hidden(message: hikari.Message, guild) -> bool:
    if not message.content or (
        not message.mentions.user_ids and not message.mentions.role_ids
    ):
        return False
    hidden_part = "||\u200b||"
    return message.content.count(hidden_part) >= 198
