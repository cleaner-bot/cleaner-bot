from expirepy import ExpiringSet


class HTTPService:
    def __init__(self) -> None:
        self.challenged_users = ExpiringSet(expires=5)
        self.deleted_messages = ExpiringSet(expires=60)
