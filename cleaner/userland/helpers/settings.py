import typing

import msgpack  # type: ignore
from coredis import Redis

from .._types import ConfigType, EntitlementsType

default_config = {
    "rules_phishing_content": 2,
    "rules_phishing_content_channels": [],
    "rules_phishing_domain_blacklisted": 2,
    "rules_phishing_domain_blacklisted_channels": [],
    "rules_phishing_domain_heuristic": 2,
    "rules_phishing_domain_heuristic_channels": [],
    "rules_phishing_embed": 2,
    "rules_phishing_embed_channels": [],
    "rules_selfbot_embed": 2,
    "rules_selfbot_embed_channels": [],
    "rules_ping_hidden": 1,
    "rules_ping_hidden_channels": [],
    "rules_ping_roles": 2,
    "rules_ping_roles_channels": [],
    "rules_ping_users_many": 2,
    "rules_ping_users_many_channels": [],
    "rules_ping_users_few": 1,
    "rules_ping_users_few_channels": [],
    "rules_ping_broad": 1,
    "rules_ping_broad_channels": [],
    "rules_advertisement_discord_invite": 1,
    "rules_advertisement_discord_invite_channels": [],
    "rules_advertisement_unsafediscord_invite": 1,
    "rules_advertisement_unsafediscord_invite_channels": [],
    "rules_advertisement_discord_unsafeinvite": 2,
    "rules_advertisement_discord_unsafeinvite_channels": [],
    "rules_emoji_mass": 0,
    "rules_emoji_mass_channels": [],
    "antispam_similar": True,
    "antispam_similar_channels": [],
    "antispam_exact": True,
    "antispam_exact_channels": [],
    "antispam_token": True,
    "antispam_token_channels": [],
    "antispam_sticker": True,
    "antispam_sticker_channels": [],
    "antispam_attachment": True,
    "antispam_attachment_channels": [],
    "antispam_anomaly": False,
    "antispam_anomaly_channels": [],
    "antispam_anomaly_score": 30,
    "antiraid_enabled": False,
    "antiraid_limit": "5/30",
    "antiraid_mode": 0,  # all/1day/3days/week
    "general_modroles": [],
    "slowmode_enabled": True,
    "slowmode_exceptions": [],
    "punishments_timeout_enabled": True,
    "punishments_verification_enabled": True,
    "verification_enabled": False,
    "verification_role": "0",
    "verification_take_role": False,
    "verification_age": 7776000,  # 3 months
    "super_verification_enabled": False,
    "super_verification_captcha": False,
    "super_verification_role": "0",
    "logging_enabled": False,
    "logging_channel": "0",
    "logging_option_join": False,
    "logging_option_join_risky": False,
    "logging_option_leave": False,
    "name_dehoisting_enabled": True,
    "name_discord_enabled": True,
    "name_advanced_enabled": False,
    "name_advanced_words": [],
    "joinguard_enabled": False,
    "joinguard_captcha": False,
    "report_enabled": False,
    "report_channel": "0",
    "branding_splash_enabled": False,
    "branding_embed_enabled": False,
    "branding_embed_title": "",
    "branding_embed_description": "",
    "access_permissions": 2,  # off/admin/admin+manager
    "access_members": [],
    "access_mfa": False,
    "antinuke_bots": 0,  # all/verified only/no
    "antinuke_webhooks": False,
    "auth_enabled": False,
    "auth_roles": {},
    "bansync_subscribed": [],
    "linkfilter_enabled": False,
    "linkfilter_channel": "0",
    "linkfilter_blockunknown": False,
}

default_entitlements = {
    "plan": 0,
    "suspended": "",
    "partnered": False,
    "access": 1,
    "antiraid": 0,  # unused
    "antispam": 0,  # unused
    "branding_splash": 1,
    "branding_embed": 1,
    "branding_vanity": 1,
    "branding_vanity_url": "",
    "contact_standard": 1,
    "contact_email": 1,
    "automod": 0,  # unused
    "name_advanced": 1,
    "joinguard": 1,
    "logging": 0,  # unused
    "logging_downloads": 1,
    "logging_retention": 3,
    "slowmode": 0,  # unused
    "statistics": 0,
    "report": 1,
    "verification": 0,  # unused
    "super_verification": 0,  # unused
    "bansync_subscription_limit": 10,
    "auth": 1,
    "linkfilter": 0,
}


async def get_config(database: Redis[bytes], guild_id: int) -> ConfigType:
    raw_config = await database.hgetall(f"guild:{guild_id}:config")
    return {**default_config, **decode_settings(raw_config)}  # type: ignore


async def set_config(
    database: Redis[bytes], guild_id: int, config: dict[str, typing.Any]
) -> None:
    raw_config = typing.cast(
        dict[str | bytes, str | bytes | int | float],
        {k: msgpack.packb(v) for k, v in config.items()},
    )
    await database.hset(f"guild:{guild_id}:config", raw_config)


async def get_entitlements(database: Redis[bytes], guild_id: int) -> EntitlementsType:
    raw_entitlements = await database.hgetall(f"guild:{guild_id}:entitlements")
    return {
        **default_entitlements,  # type: ignore
        **decode_settings(raw_entitlements),
    }


async def set_entitlements(
    database: Redis[bytes], guild_id: int, entitlements: dict[str, typing.Any]
) -> None:
    raw_entitlements = typing.cast(
        dict[str | bytes, str | bytes | int | float],
        {k: msgpack.packb(v) for k, v in entitlements.items()},
    )
    await database.hset(f"guild:{guild_id}:entitlements", raw_entitlements)


def decode_settings(dictionary: dict[bytes, bytes]) -> dict[str, str | int | bool]:
    return {key.decode(): msgpack.unpackb(value) for key, value in dictionary.items()}
