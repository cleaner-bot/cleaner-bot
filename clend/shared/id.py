from datetime import timedelta

from hikari import Snowflake
from hikari.internal.time import utc_datetime


def time_passed_since(id: Snowflake) -> timedelta:
    now = utc_datetime()
    return now - id.created_at
