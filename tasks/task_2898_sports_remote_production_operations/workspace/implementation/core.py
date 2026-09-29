"""Foundation layer: logical clock, ids, rounding, response envelope, auth, payloads.

Every structural name in here is taken from SCAFFOLD.yaml `response_envelope` /
`validations` and from PRD.md sections 2.1 - 2.8.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# PRD 2.4: the clock's value at server startup is exactly 2026-08-01T00:00:00Z and the
# server must not fall back to wall-clock time before the clock is first set.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_runtime = {"now": CLOCK_START, "seq": 0}

ROLE_PRODUCTION_MANAGER = "ProductionManager"
ROLE_TECHNICAL_DIRECTOR = "TechnicalDirector"
ROLE_LEAGUE_OPERATIONS = "LeagueOperations"
ROLE_UNION_STEWARD = "UnionSteward"
ROLE_CREW_MEMBER = "CrewMember"

ALL_ROLES = (
    ROLE_PRODUCTION_MANAGER,
    ROLE_TECHNICAL_DIRECTOR,
    ROLE_LEAGUE_OPERATIONS,
    ROLE_UNION_STEWARD,
    ROLE_CREW_MEMBER,
)

# The four operator roles that share every GET endpoint and the clock endpoint.
OPERATOR_ROLES = (
    ROLE_PRODUCTION_MANAGER,
    ROLE_TECHNICAL_DIRECTOR,
    ROLE_LEAGUE_OPERATIONS,
    ROLE_UNION_STEWARD,
)


# ---------------------------------------------------------------------------
# logical clock / identity / ordering
# ---------------------------------------------------------------------------
def now_utc():
    return _runtime["now"]


def set_now(value):
    _runtime["now"] = value


def next_seq():
    _runtime["seq"] += 1
    return _runtime["seq"]


def new_id():
    return str(uuid.uuid4())


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if value is None:
        return None
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def parse_dt(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except Exception:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def whole_minutes(start, end):
    """Whole minutes between two instants, truncated toward zero (PRD 2.8)."""
    micros = (end - start) // timedelta(microseconds=1)
    sign = -1 if micros < 0 else 1
    return sign * (abs(micros) // 60000000)


def minutes_later(value, minutes):
    return value + timedelta(minutes=minutes)


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def rhu(value, places=0):
    """round half up to `places` decimal places; value must be a Decimal or int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def money(value):
    """Round half up to whole cents, returned as int."""
    return int(rhu(value, 0))


def two_dp(value):
    return float(rhu(value, 2))


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


# ---------------------------------------------------------------------------
# response envelope (SCAFFOLD response_envelope / PRD 2.2)
# ---------------------------------------------------------------------------
_ID_ALPHABET = string.ascii_uppercase + string.digits


def _request_meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20)),
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }
    if extra:
        meta.update(extra)
    return meta


def respond_object(data, http_status=200):
    body = {"meta": _request_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), http_status


def respond_list(items, page_meta, http_status=200):
    body = {"meta": _request_meta(page_meta), "response_type": "array", "data": items}
    return jsonify(body), http_status


def respond_error(error_id, message, http_status):
    body = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# auth (validations priority 1 and 2 / PRD 2.1)
# ---------------------------------------------------------------------------
def require_roles(*allowed):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    "X-User-ID and X-User-Role headers are required and must be non-empty.",
                    401,
                )
            if role not in ALL_ROLES or role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %r is not permitted on this endpoint." % role,
                    403,
                )
            g.user_id = user_id
            g.user_role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "user_role", None)


# ---------------------------------------------------------------------------
# pagination (SCAFFOLD pagination_fields / pagination_defaults, PRD 2.3)
# ---------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise invalid("Query parameter %s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise invalid("Query parameter %s must be an integer." % name)
    return -int(digits) if negative else int(digits)


def read_pagination():
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = PAGE_LIMIT_DEFAULT
    elif limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise invalid("limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if offset is None:
        offset = PAGE_OFFSET_DEFAULT
    elif offset < 0:
        raise invalid("offset must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise invalid("Query parameter %s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def page_result(rows, serializer):
    limit, offset = read_pagination()
    total = len(rows)
    window = rows[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return respond_list([serializer(row) for row in window], meta)


# ---------------------------------------------------------------------------
# request-body schema validation (validations priority 3 / PRD 2.7 rung 3)
# ---------------------------------------------------------------------------
class Payload:
    def __init__(self, raw=None):
        if raw is None:
            raw = request.get_json(silent=True)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise invalid("Request body must be a JSON object.")
        self.data = raw

    def present(self, key):
        return key in self.data and self.data[key] is not None

    def _missing(self, key, required, default):
        if required:
            raise invalid("Field %s is required." % key)
        return default

    def string(self, key, required=True, default=None, allow_blank=False):
        if not self.present(key):
            return self._missing(key, required, default)
        value = self.data[key]
        if not isinstance(value, str):
            raise invalid("Field %s must be a string." % key)
        if not allow_blank and value.strip() == "":
            raise invalid("Field %s must be a non-empty string." % key)
        return value

    def integer(self, key, required=True, default=None, minimum=None, maximum=None):
        if not self.present(key):
            return self._missing(key, required, default)
        value = self.data[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("Field %s must be an integer." % key)
        if minimum is not None and value < minimum:
            raise invalid("Field %s must be at least %s." % (key, minimum))
        if maximum is not None and value > maximum:
            raise invalid("Field %s must be at most %s." % (key, maximum))
        return value

    def number(self, key, required=True, default=None, minimum=None):
        if not self.present(key):
            return self._missing(key, required, default)
        value = self.data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid("Field %s must be a number." % key)
        if minimum is not None and value < minimum:
            raise invalid("Field %s must be at least %s." % (key, minimum))
        return value

    def boolean(self, key, required=True, default=None):
        if not self.present(key):
            return self._missing(key, required, default)
        value = self.data[key]
        if not isinstance(value, bool):
            raise invalid("Field %s must be a boolean." % key)
        return value

    def enum(self, key, allowed, required=True, default=None):
        if not self.present(key):
            return self._missing(key, required, default)
        value = self.data[key]
        if not isinstance(value, str) or value not in allowed:
            raise invalid("Field %s must be one of %s." % (key, ", ".join(allowed)))
        return value

    def instant(self, key, required=True, default=None):
        if not self.present(key):
            return self._missing(key, required, default)
        value = self.data[key]
        if not isinstance(value, str):
            raise invalid("Field %s must be an ISO-8601 instant string." % key)
        parsed = parse_dt(value)
        if parsed is None:
            raise invalid("Field %s must be a well-formed ISO-8601 instant." % key)
        return parsed

    def raw_instant(self, key, required=True):
        """Returns (present, parsed_or_None) without raising on a malformed instant."""
        if not self.present(key):
            if required:
                raise invalid("Field %s is required." % key)
            return False, None
        value = self.data[key]
        if not isinstance(value, str):
            raise invalid("Field %s must be an ISO-8601 instant string." % key)
        return True, parse_dt(value)

    def enum_array(self, key, allowed, required=True, non_empty=True):
        if not self.present(key):
            return self._missing(key, required, None)
        value = self.data[key]
        if not isinstance(value, list):
            raise invalid("Field %s must be an array." % key)
        if non_empty and len(value) == 0:
            raise invalid("Field %s must be a non-empty array." % key)
        for item in value:
            if not isinstance(item, str) or item not in allowed:
                raise invalid("Field %s elements must be one of %s." % (key, ", ".join(allowed)))
        return list(value)
