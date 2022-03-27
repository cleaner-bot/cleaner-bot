import hikari


def has_unescaped(content: str, key: str) -> bool:
    current_position: int | None = None
    while current_position is None or current_position < len(content):
        try:
            current_position = content.index(
                key, None if current_position is None else current_position + 1
            )
        except ValueError:
            break
        before, after = content[:current_position], content[current_position:]
        if before.count("`") % 2 == 0:
            return True
        elif after.count("`") == 0:
            return True

    return False


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
    return has_unescaped(message.content, "@everyone") or has_unescaped(
        message.content, "@here"
    )


def ping_hidden(message: hikari.Message, guild) -> bool:
    if not message.content or (
        not message.mentions.user_ids and not message.mentions.role_ids
    ):
        return False
    hidden_part = "||\u200b||"
    return message.content.count(hidden_part) >= 198
