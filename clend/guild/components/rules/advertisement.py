import re

import hikari

discord_invite = re.compile(
    r"(?:https?://)?(?:discord\.gg/|discord(app)?\.com/invite/)([a-zA-Z0-9-]+)",
    re.IGNORECASE,
)


def advertisement_discord(message: hikari.Message, guild) -> bool:
    if not message.content:
        return False
    return discord_invite.search(message.content) is not None
