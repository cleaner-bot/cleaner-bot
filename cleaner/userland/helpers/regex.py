import re

DISCORD_INVITE = re.compile(
    r"(?:https?://)?(?:discord\.gg/|discord(app)?\.com/invite/)"
    r"([a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])",
    re.IGNORECASE,
)
