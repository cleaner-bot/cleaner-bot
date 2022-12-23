import os
from urllib.parse import urlencode

from hikari import GatewayBot, OAuth2Scope, Permissions
from hikari.urls import BASE_URL

INVITE_PERMISSIONS = (
    Permissions.BAN_MEMBERS
    | Permissions.KICK_MEMBERS
    | Permissions.SEND_MESSAGES
    | Permissions.VIEW_CHANNEL
    | Permissions.EMBED_LINKS
    | Permissions.MANAGE_MESSAGES
    | Permissions.MANAGE_GUILD
    | Permissions.MANAGE_CHANNELS
    | Permissions.MANAGE_ROLES
    | Permissions.MANAGE_NICKNAMES
    | Permissions.MANAGE_WEBHOOKS
    | Permissions.MODERATE_MEMBERS
)


def generate_invite(
    bot: GatewayBot, with_bot: bool, with_dashboard: bool, state: str = ""
) -> str:
    base = "/oauth2/authorize"
    client_id = os.getenv("DISCORD_CLIENT_ID")
    if client_id is None:
        # no client id override, so just assume bot id == client id
        me = bot.cache.get_me()
        assert me is not None, "dont care enough to handle this"
        client_id = str(me.id)

    scopes: list[OAuth2Scope] = []
    if with_bot:
        scopes.extend(
            (
                OAuth2Scope.BOT,
                OAuth2Scope.APPLICATIONS_COMMANDS,
            )
        )

    if with_dashboard:
        scopes.extend(
            (
                OAuth2Scope.IDENTIFY,
                OAuth2Scope.GUILDS,
            )
        )

    query = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scopes),
        "prompt": "none",
    }

    if with_bot:
        query["permissions"] = str(int(INVITE_PERMISSIONS))

    if with_dashboard:
        query["redirect_uri"] = "https://cleanerbot.xyz/oauth-comeback"
        if state:
            query["state"] = state

    return f"{BASE_URL}{base}?{urlencode(query)}"
