import attr

from hikari.traits import GatewayBotAware
from hikari.events.base_events import Event


@attr.define()
class FastTimerEvent(Event):
    """Fires every 10 seconds."""

    app: GatewayBotAware = attr.field()

    sequence: int = attr.field()


@attr.define()
class SlowTimerEvent(Event):
    """Fires every 5 minutes."""

    app: GatewayBotAware = attr.field()

    sequence: int = attr.field()
