import hikari
from cleaner_data.normalize import normalize
from cleaner_data.url import get_urls
from hikari.internal.time import utc_datetime


def user_mentions(message: hikari.Message) -> int:
    return len(message.user_mentions_ids) if message.user_mentions_ids else 0


def role_mentions(message: hikari.Message) -> int:
    return len(message.role_mention_ids) if message.role_mention_ids else 0


def embeds(message: hikari.Message) -> int:
    return len(message.embeds)


def attachments(message: hikari.Message) -> int:
    return len(message.attachments)


def replied(message: hikari.Message) -> int:
    return 0 if message.referenced_message is None else 1


def message_length(message: hikari.Message) -> int:
    return len(message.content) if message.content else 0


def normalized_message_length(message: hikari.Message) -> int:
    return len(normalize(message.content)) if message.content else 0


def normalized_words(message: hikari.Message) -> int:
    return len(normalize(message.content).split()) if message.content else 0


def message_links(message: hikari.Message) -> int:
    if message.content is None:
        return 0
    return sum(1 for _ in get_urls(message.content))


def author_age_days(message: hikari.Message) -> int:
    now = utc_datetime()
    age = (now - message.author.created_at).days
    return age


def author_age_weeks(message: hikari.Message) -> int:
    now = utc_datetime()
    age = (now - message.author.created_at).days
    return age // 7


scoring = [
    user_mentions,
    role_mentions,
    embeds,
    attachments,
    replied,
    message_length,
    normalized_message_length,
    message_links,
    author_age_days,
    author_age_weeks,
]


def raw_score_message(message: hikari.Message) -> dict[str, int]:
    return {func.__name__: func(message) for func in scoring}
