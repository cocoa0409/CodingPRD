"""Foundation layer for the Event Cinema Booking API.

Holds the logical clock, the in-memory store, the error catalogue, the §2.2
response envelope, the auth/RBAC middleware, the schema helpers and the
pagination helpers.  Nothing is seeded here: a fresh boot starts with every
collection empty and a logical clock reading exactly 2026-09-01T00:00:00Z.
"""
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalogue (§5) -- error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SOD_VIOLATION": 403,
    # not found
    "ERR_DISTRIBUTOR_NOT_FOUND": 404,
    "ERR_CIRCUIT_NOT_FOUND": 404,
    "ERR_THEATER_NOT_FOUND": 404,
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_SCREENING_NOT_FOUND": 404,
    "ERR_KEY_NOT_FOUND": 404,
    "ERR_DELIVERY_NOT_FOUND": 404,
    "ERR_ENCORE_WINDOW_NOT_FOUND": 404,
    "ERR_FEED_EVENT_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_SHOWTIME_PLAN_INVALID": 400,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_BOOKING_NOT_REPORTABLE": 409,
    "ERR_BOOKING_LINE_NOT_COMMITTED": 409,
    "ERR_DELIVERY_NOT_VERIFIED": 409,
    "ERR_KEY_NOT_ISSUABLE": 409,
    "ERR_SETTLEMENT_ALREADY_CLOSED": 409,
    # business: safety / rights
    "ERR_TERRITORY_UNLICENSED": 422,
    "ERR_RIGHTS_WINDOW_VIOLATION": 422,
    "ERR_RIGHTS_EXPIRED": 422,
    # business: referential / temporal
    "ERR_SCREEN_OVERLAP_CONFLICT": 409,
    "ERR_SCREEN_BUFFER_CONFLICT": 409,
    "ERR_KEY_WINDOW_OVERLAP": 409,
    "ERR_SCREEN_POOL_EXHAUSTED": 409,
    "ERR_DUPLICATE_CIRCUIT_CODE": 409,
    "ERR_MAX_SCREEN_COMMITMENT_EXCEEDED": 422,
    "ERR_COUNTER_LIMIT_REACHED": 409,
    "ERR_DUPLICATE_BOOKING_LINE": 409,
    # business: fiscal / threshold
    "ERR_GUARANTEE_BELOW_FLOOR": 422,
    "ERR_GUARANTEE_ABOVE_CEILING": 422,
    "ERR_MIN_SCREENS_NOT_MET": 422,
    "ERR_UNREPORTED_ATTENDANCE": 422,
    "ERR_FEED_OUTAGE_TOO_SHORT": 422,
    "ERR_MAKEGOOD_LINE_NOT_APPLICABLE": 422,
    "ERR_ENCORE_DENOMINATOR_ZERO": 422,
    "ERR_ENCORE_WINDOW_INVALID": 422,
    "ERR_ENCORE_NOT_ELIGIBLE": 422,
    "ERR_DELIVERY_LEAD_VIOLATION": 422,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words.capitalize() + "."


# ---------------------------------------------------------------------------
# Roles (§1.7) and identity scheme (§2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "PlatformOps",
    "ProgrammingManager",
    "Distributor",
    "Exhibitor",
    "Theater",
    "FinanceOps",
    "ContentOfficer",
)

# Roles whose X-User-ID must resolve to an existing instance of a backing entity.
ENTITY_BACKED_ROLES = {
    "Distributor": "distributors",
    "Exhibitor": "circuits",
    "Theater": "theaters",
}

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"


# ---------------------------------------------------------------------------
# Decimal / time helpers
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    """round_half_up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """round_half_up to a whole cent, returned as an int."""
    return int(rhu(value, 0))


def floor_int(value):
    """Truncate a Decimal/number toward zero, as an int."""
    return int(D(value))


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_hours(dt, hours):
    return dt + timedelta(hours=int(hours))


def floor_days(later, earlier):
    """Whole days between two instants, truncated."""
    return int((later - earlier).total_seconds() // 86400)


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(text):
    """Parse an ISO-8601 datetime; returns None when unparseable."""
    if isinstance(text, datetime):
        return text if text.tzinfo else text.replace(tzinfo=UTC)
    if not isinstance(text, str):
        return None
    m = _DT_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1_000_000))
    tzpart = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body = tzpart[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


# ---------------------------------------------------------------------------
# In-memory store -- EMPTY on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "distributors",
    "circuits",
    "theaters",
    "titles",
    "bookings",
    "booking_lines",
    "screenings",
    "encore_windows",
    "content_deliveries",
    "encryption_keys",
    "feed_events",
    "settlements",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def new_row(kind, **fields):
    row = {
        "_kind": kind,
        "_seq": db.next_seq(),
        "id": str(uuid.uuid4()),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump the audit fields. Cascades call this too."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.clock
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dump(row, extra=None):
    if row is None:
        return None
    out = {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}
    if extra:
        out.update({k: jsonable(v) for k, v in extra.items()})
    return out


# ---------------------------------------------------------------------------
# Response envelope (§2.2)
# ---------------------------------------------------------------------------
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _meta():
    token = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    return {
        "api_request_id": "req_" + token,
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }


def respond_object(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": jsonable(data)}),
        status,
    )


def respond_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return (
        jsonify({"meta": meta, "response_type": "array", "data": jsonable(items)}),
        status,
    )


def respond_error(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# Auth (validation priorities 1 and 2)
# ---------------------------------------------------------------------------
def endpoint(*roles):
    """Declare the roles permitted on a route and enforce tiers 1-2."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = (request.headers.get(HDR_USER) or "").strip()
            role = (request.headers.get(HDR_ROLE) or "").strip()
            if not user_id or not role:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ROLES or role not in allowed:
                raise ApiError("ERR_FORBIDDEN")
            backing = ENTITY_BACKED_ROLES.get(role)
            if backing is not None:
                if user_id not in getattr(db, backing):
                    raise ApiError("ERR_FORBIDDEN")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "role", None)


def segregation_of_duties(*principal_ids):
    """Tier 3.  Refuse when the acting operator is one of the named principals."""
    acting = actor_id()
    for principal in principal_ids:
        if principal and acting == principal:
            raise ApiError("ERR_SOD_VIOLATION")


# ---------------------------------------------------------------------------
# Tier 4 -- request schema helpers (ERR_INVALID_REQUEST, HTTP 400)
# ---------------------------------------------------------------------------
_MISSING = object()


def bad_request(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


def body():
    """Parse the JSON body. An absent body behaves as an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


def _fetch(src, key, required):
    if key not in src or src[key] is None:
        if required:
            bad_request("Field '%s' is required." % key)
        return _MISSING
    return src[key]


def f_str(src, key, required=True, allow_empty=False):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad_request("Field '%s' must not be empty." % key)
    return value


def f_enum(src, key, domain, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in domain:
        bad_request("Field '%s' must be one of %s." % (key, ", ".join(domain)))
    return value


def f_bool(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def f_int(src, key, required=True, default=None, minimum=None, maximum=None, choices=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be at most %s." % (key, maximum))
    if choices is not None and value not in choices:
        bad_request("Field '%s' must be one of %s." % (key, list(choices)))
    return value


def f_num(src, key, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad_request("Field '%s' must be a number." % key)
    dec = D(value)
    if minimum is not None and dec < D(minimum):
        bad_request("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and dec > D(maximum):
        bad_request("Field '%s' must be at most %s." % (key, maximum))
    return dec


def f_dt(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        bad_request("Field '%s' must be an ISO-8601 UTC timestamp." % key)
    return parsed


def f_str_list(src, key, required=True, default=None, non_empty=True, length=2):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % key)
    if non_empty and len(value) == 0:
        bad_request("Field '%s' must not be empty." % key)
    for member in value:
        if not isinstance(member, str) or len(member) != length:
            bad_request("Field '%s' members must be %s-letter codes." % (key, length))
    return list(value)


# ---------------------------------------------------------------------------
# Query-string helpers
# ---------------------------------------------------------------------------
def q_str(key, default=None):
    if key not in request.args:
        return default
    value = request.args.get(key)
    if value is None or value == "":
        return default
    return value


def q_enum(key, domain, default=None):
    value = q_str(key)
    if value is None:
        return default
    if value not in domain:
        bad_request("Query parameter '%s' must be one of %s." % (key, ", ".join(domain)))
    return value


def q_bool(key, default=None):
    value = q_str(key)
    if value is None:
        return default
    low = value.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    bad_request("Query parameter '%s' must be true or false." % key)


def q_int(key, default=None, minimum=None, maximum=None):
    value = q_str(key)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        bad_request("Query parameter '%s' must be an integer." % key)
    if minimum is not None and parsed < minimum:
        bad_request("Query parameter '%s' must be at least %s." % (key, minimum))
    if maximum is not None and parsed > maximum:
        bad_request("Query parameter '%s' must be at most %s." % (key, maximum))
    return parsed


PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def pagination():
    limit = q_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = q_int("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows):
    """Apply limit/offset to an already-ordered row list and emit the envelope."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return respond_list([dump(r) for r in page], total, limit, offset)


def page(rows):
    """Apply limit/offset to an already-ordered row list, returning rows + meta."""
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], total, limit, offset


# ---------------------------------------------------------------------------
# Domain option sets used by several layers
# ---------------------------------------------------------------------------
CIRCUIT_CODES = ("NET_30", "NET_60", "GROSS_ON_GROSS", "FOUR_WALL")
CREDIT_RATINGS = ("A", "B", "C")
CONTENT_TYPES = ("CONCERT", "ANNIVERSARY", "FAITH", "LIVE_BROADCAST", "SPECIAL")
DELIVERY_METHODS = ("SATELLITE", "FILE", "BOTH")
FAILURE_TYPES = ("FEED_LOSS", "CONTENT_FAILURE", "SATELLITE_OUTAGE", "KEY_FAILURE")
REVOCATION_REASONS = ("FEED_LOSS", "CONTENT_FAILURE")
RESOLUTION_OUTCOMES = ("RECOVERED", "ABANDONED")
REPORT_OUTCOMES = ("SCREENED", "SKIPPED_INCOMPLETE")

DISTRIBUTOR_STATUS = ("ACTIVE", "SUSPENDED")
CIRCUIT_STATUS = ("PENDING", "ACCREDITED", "SUSPENDED")
THEATER_STATUS = ("ACTIVE", "DARK", "SUSPENDED")
TITLE_STATUS = (
    "DRAFT",
    "BOOKABLE",
    "CLEARED",
    "RIGHTS_EXPIRED",
    "WITHDRAWN",
    "ARCHIVED",
)
BOOKING_STATUS = (
    "DRAFT",
    "PENDING_APPROVAL",
    "COUNTERED",
    "APPROVED",
    "ON_SALE",
    "ON_HOLD",
    "CONFIRMED",
    "CANCELLED",
    "SETTLED",
    "TERMINAL",
)
EXHIBIT_STATE = ("PROPOSED", "COMMITTED", "RELEASED")
SCREENING_STATE = (
    "SCHEDULED",
    "SCREENED",
    "SKIPPED_INCOMPLETE",
    "SKIPPED_CANCELLED",
    "VOID",
)
ENCORE_WINDOW_STATUS = ("DRAFT", "SCHEDULED", "WITHDRAWN", "EXPIRED")
DELIVERY_STATUS = ("SCHEDULED", "DELIVERED", "VERIFIED", "FAILED")
ISSUANCE_STATUS = ("PENDING", "ISSUED", "REVOKED")
VALIDITY_STATE = ("NOT_YET_VALID", "VALID", "EXPIRED")
FEED_EVENT_STATE = ("DETECTED", "CONFIRMED", "VOIDED", "RESOLVED")
SETTLEMENT_STATUS = ("OPEN", "CLOSED", "REOPENED")

TITLE_TERMINAL = ("ARCHIVED",)
BOOKING_TERMINAL = ("TERMINAL",)
SCREENING_TERMINAL = ("SCREENED", "SKIPPED_INCOMPLETE", "SKIPPED_CANCELLED", "VOID")
DELIVERY_TERMINAL = ("VERIFIED", "FAILED")
KEY_TERMINAL = ("REVOKED",)
FEED_EVENT_TERMINAL = ("RESOLVED",)
ENCORE_TERMINAL = ("WITHDRAWN", "EXPIRED")