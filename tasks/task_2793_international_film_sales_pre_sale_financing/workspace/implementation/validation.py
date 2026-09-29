"""Auth (PRD 2.1), request-shape validation (PRD 2.7 rung four) and pagination."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from errors import ApiError
from util import parse_instant, to_decimal, to_int

ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "Buyer",
    "DeliveryManager",
    "CollectionAgent",
    "Lender",
    "PlatformAdmin",
)

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def require_roles(*allowed):
    """Rung one then rung two of the rejection ladder."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not str(user_id).strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = str(user_id)
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.get("user_id")


def actor_role():
    return g.get("role")


def _bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


class Body:
    """Thin typed reader over the JSON request body."""

    def __init__(self, raw):
        self.raw = raw if isinstance(raw, dict) else {}

    def has(self, key):
        return key in self.raw and self.raw[key] is not None

    def present(self, key):
        return key in self.raw

    # ------------------------------------------------------------- strings
    def req_string(self, key):
        value = self.raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise _bad("Field '%s' must be a non-empty string." % key)
        return value.strip()

    def opt_string(self, key, default=None):
        if not self.has(key):
            return default
        return self.req_string(key)

    # --------------------------------------------------------------- enums
    def req_enum(self, key, allowed):
        value = self.raw.get(key)
        if not isinstance(value, str) or value not in allowed:
            raise _bad(
                "Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed)))
            )
        return value

    def opt_enum(self, key, allowed, default=None):
        if not self.has(key):
            return default
        return self.req_enum(key, allowed)

    # ------------------------------------------------------------- numbers
    def _number(self, key, value, minimum, maximum, exclusive_min, exclusive_max):
        number = to_decimal(value)
        if number is None:
            raise _bad("Field '%s' must be a number." % key)
        if minimum is not None:
            if exclusive_min and number <= minimum:
                raise _bad("Field '%s' must be greater than %s." % (key, minimum))
            if not exclusive_min and number < minimum:
                raise _bad("Field '%s' must be at least %s." % (key, minimum))
        if maximum is not None:
            if exclusive_max and number >= maximum:
                raise _bad("Field '%s' must be less than %s." % (key, maximum))
            if not exclusive_max and number > maximum:
                raise _bad("Field '%s' must be at most %s." % (key, maximum))
        return number

    def req_number(
        self, key, minimum=None, maximum=None, exclusive_min=False, exclusive_max=False
    ):
        if key not in self.raw or self.raw[key] is None:
            raise _bad("Field '%s' is required." % key)
        return self._number(
            key, self.raw[key], minimum, maximum, exclusive_min, exclusive_max
        )

    def opt_number(
        self,
        key,
        minimum=None,
        maximum=None,
        exclusive_min=False,
        exclusive_max=False,
        default=None,
    ):
        if not self.has(key):
            return default
        return self._number(
            key, self.raw[key], minimum, maximum, exclusive_min, exclusive_max
        )

    def nullable_number(
        self, key, minimum=None, maximum=None, exclusive_min=False, exclusive_max=False
    ):
        """Present-and-null is a legitimate value (waterfall tier cap_usd)."""
        if key not in self.raw or self.raw[key] is None:
            return None
        return self._number(
            key, self.raw[key], minimum, maximum, exclusive_min, exclusive_max
        )

    def req_int(self, key, minimum=None, maximum=None):
        if key not in self.raw or self.raw[key] is None:
            raise _bad("Field '%s' is required." % key)
        number = to_int(self.raw[key])
        if number is None:
            raise _bad("Field '%s' must be an integer." % key)
        if minimum is not None and number < minimum:
            raise _bad("Field '%s' must be at least %s." % (key, minimum))
        if maximum is not None and number > maximum:
            raise _bad("Field '%s' must be at most %s." % (key, maximum))
        return number

    def opt_int(self, key, minimum=None, maximum=None, default=None):
        if not self.has(key):
            return default
        return self.req_int(key, minimum, maximum)

    # -------------------------------------------------------------- others
    def req_bool(self, key):
        value = self.raw.get(key)
        if not isinstance(value, bool):
            raise _bad("Field '%s' must be a boolean." % key)
        return value

    def opt_bool(self, key, default=None):
        if not self.has(key):
            return default
        return self.req_bool(key)

    def req_instant(self, key):
        if key not in self.raw or self.raw[key] is None:
            raise _bad("Field '%s' is required." % key)
        instant = parse_instant(self.raw[key])
        if instant is None:
            raise _bad("Field '%s' must be an ISO 8601 instant." % key)
        return instant

    def opt_instant(self, key, default=None):
        if not self.has(key):
            return default
        return self.req_instant(key)

    def req_id(self, key):
        value = self.raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise _bad("Field '%s' must be an id string." % key)
        return value.strip()


def body():
    return Body(request.get_json(silent=True, force=True))


def raw_id(key):
    """Read a body FK for the existence rung without failing on absence."""
    payload = request.get_json(silent=True, force=True)
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is None:
        return None
    return value


def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        limit = to_int(args.get("limit"))
        if limit is None or limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise _bad("Query parameter 'limit' is out of bounds.")
    if "offset" in args:
        offset = to_int(args.get("offset"))
        if offset is None or offset < OFFSET_MIN:
            raise _bad("Query parameter 'offset' is out of bounds.")
    return limit, offset


def page(items, serializer):
    limit, offset = pagination()
    total = len(items)
    window = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return [serializer(row) for row in window], meta
