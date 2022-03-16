import math

import hikari
from hikari.internal.time import utc_datetime


def calculate_risk_score(user: hikari.User) -> float:
    age = (utc_datetime() - user.created_at).total_seconds() / 86400
    ground = 9
    risk = ground / math.sqrt(age + (ground - 1) * ground) - 0.1
    if user.avatar_hash is None:
        risk += 0.17
    else:
        risk -= 0.04
    if user.flags & (
        hikari.UserFlag.HYPESQUAD_BALANCE
        | hikari.UserFlag.HYPESQUAD_BRAVERY
        | hikari.UserFlag.HYPESQUAD_BRILLIANCE
    ):
        risk -= 0.01
    if user.flags & hikari.UserFlag.EARLY_SUPPORTER:
        risk -= 0.05
    if user.flags & (
        hikari.UserFlag.PARTNERED_SERVER_OWNER
        | hikari.UserFlag.EARLY_VERIFIED_DEVELOPER
    ):
        risk -= 0.1
    if user.flags & (
        hikari.UserFlag.DISCORD_CERTIFIED_MODERATOR
        | hikari.UserFlag.HYPESQUAD_EVENTS
        | hikari.UserFlag.DISCORD_EMPLOYEE
    ):
        risk = 0
    return max(0, min(1, risk))
