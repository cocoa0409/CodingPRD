"""Request context passed to every handler."""

from errors import ApiError
from utils import num, parse_iso


class Request:
    def __init__(self, method, path, params, body, query, headers, principal):
        self.method = method
        self.path = path
        self.params = params or {}
        self.body = body if isinstance(body, dict) else {}
        self.query = query or {}
        self.headers = headers or {}
        self.principal = principal

    # -- query helpers -----------------------------------------------------
    def q(self, key, default=None):
        value = self.query.get(key)
        if value is None or value == "":
            return default
        return value

    def q_int(self, key, default=None):
        value = self.q(key)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "query parameter %s must be an integer" % key)

    def q_dt(self, key, default=None):
        value = self.q(key)
        if value is None:
            return default
        parsed = parse_iso(value)
        if parsed is None:
            raise ApiError("ERR_INVALID_REQUEST", "query parameter %s must be an instant" % key)
        return parsed

    def q_num(self, key, default=None):
        value = self.q(key)
        if value is None:
            return default
        parsed = num(value)
        if parsed is None:
            raise ApiError("ERR_INVALID_REQUEST", "query parameter %s must be a number" % key)
        return parsed

    # -- body helpers ------------------------------------------------------
    def b(self, key, default=None):
        value = self.body.get(key)
        return default if value is None else value

    def path_id(self, name):
        return self.params.get(name)

    def idempotency_key(self):
        return self.headers.get("Idempotency-Key") or self.body.get("idempotency_key")