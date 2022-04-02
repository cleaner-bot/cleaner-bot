import attr

from hikari.traits import RESTAware
from hikari.events.base_events import Event


@attr.define()
class TimerEvent(Event):
    app: RESTAware = attr.field()

    sequence: int = attr.field()
