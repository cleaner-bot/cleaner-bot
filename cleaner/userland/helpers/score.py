from datetime import datetime, timezone

import hikari
from decancer_py import parse

from .url import get_urls


def score_message(message: hikari.Message) -> list[int]:
    assert message.member

    content = message.content or ""
    normalized = [x.lower() for x in parse(content).split()]
    now = datetime.now(timezone.utc)

    scores = [
        # mentions
        int(message.mentions_everyone or False),
        int("@everyone" in content or "@here" in content),
        len(message.user_mentions_ids) if message.user_mentions_ids else 0,
        len(message.role_mention_ids) if message.role_mention_ids else 0,
        # message length
        len(content),
        len(normalized),  # words
        len(set(normalized)),  # unique words
        # metadata
        sum(1 for _ in get_urls(content)),
        len(message.attachments),
        len(message.embeds),
        len(message.stickers),
        int(message.type),
        int(message.flags),
        int(message.is_tts),
        # member metadata
        (now - message.member.created_at).days,
        (now - message.member.joined_at).days,
    ]

    return scores
