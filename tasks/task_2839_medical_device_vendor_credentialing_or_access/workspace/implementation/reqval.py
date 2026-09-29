"""Validation ladder rungs 1-4 (PRD 2.9): authentication, authorization,
request well-formedness and instant ordering.
"""
from flask import request

import db
from errors import ApiError
from envelope import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from timeutil import fmt_instant, parse_instant


# ---------------------------------------------------------------- rungs 1 & 2
def authenticate(allowed_roles):
    """Rung 1 (ERR_UNAUTHENTICATED) then rung 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in db.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# ------------------------------------------------------------------- rung 3
class Body(object):
    """Reads request-body fields in the endpoint's declared field order."""

    def __init__(self, raw):
        self.raw = raw

    def _present(self, name):
        return name in self.raw and self.raw[name] is not None

    def _bad(self, name, detail):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field '%s' is invalid: %s." % (name, detail)
        )

    def _missing(self, name):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)

    # -- typed readers ----------------------------------------------------
    def string(self, name, required=True, default=None):
        if not self._present(name):
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if not isinstance(value, str):
            self._bad(name, "expected a string")
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None):
        if not self._present(name):
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if isinstance(value, bool) or not isinstance(value, int):
            self._bad(name, "expected an integer")
        if minimum is not None and value < minimum:
            self._bad(name, "must be >= %d" % minimum)
        if maximum is not None and value > maximum:
            self._bad(name, "must be <= %d" % maximum)
        return value

    def boolean(self, name, required=True, default=None):
        if not self._present(name):
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if not isinstance(value, bool):
            self._bad(name, "expected a boolean")
        return value

    def enum(self, name, domain, required=True, default=None):
        if not self._present(name):
            if required:
                self._missing(name)
            return default
        value = self.raw[name]
        if not isinstance(value, str) or value not in domain:
            self._bad(name, "must be one of %s" % ", ".join(domain))
        return value

    def instant(self, name, required=True, default=None):
        """Returns (canonical_string, aware_datetime).

        A caller-supplied instant is canonicalised to the three-fractional-digit
        UTC form before it is stored, so every instant this server emits — and
        every stored-instant equality the specification relies on — has one
        single shape (PRD 2.5).
        """
        if not self._present(name):
            if required:
                self._missing(name)
            return default, None
        value = self.raw[name]
        if not isinstance(value, str):
            self._bad(name, "expected an ISO-8601 UTC instant string")
        parsed = parse_instant(value)
        if parsed is None:
            self._bad(name, "is not a parseable ISO-8601 UTC instant")
        return fmt_instant(parsed), parsed


def read_body():
    """Rung 3: the body must be absent, empty, or a JSON object."""
    raw_bytes = request.get_data(cache=True)
    if not raw_bytes or not raw_bytes.strip():
        return Body({})
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return Body(parsed)


# ------------------------------------------------------------- pagination
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def pagination_params():
    """PRD 2.3: limit defaults to 10 and lies in 1..100; offset defaults to 0 and is not negative."""
    limit = _query_int("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _query_int("offset", DEFAULT_OFFSET, 0, None)
    return limit, offset


def query_enum(name, domain):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in domain:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(domain)),
        )
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


# ------------------------------------------------------------------- rung 4
def require_ordered(earlier, later):
    """Rung 4: any pair of instants supplied together must be correctly ordered."""
    if earlier is None or later is None:
        return
    if not (later > earlier):
        raise ApiError("ERR_INVALID_TIME_RANGE")
