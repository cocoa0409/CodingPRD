"""Foundation: logical clock, in-memory store, error catalogue, response
envelope, auth, and validation helpers (PRD section 2).

Nothing is seeded: a fresh boot starts with zero rows and a logical clock
reading exactly 2026-09-01T00:00:00Z (PRD section 2.4).
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
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_OUTSIDE_TIME_WINDOW": 409,
    "ERR_DROP_LIMIT_REACHED": 409,
    "ERR_STATION_AT_CAPACITY": 409,
    "ERR_HOST_UNAVAILABLE": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_GIFT_CARD_INSUFFICIENT": 409,
    "ERR_GIFT_CARD_NOT_LINKED": 409,
    "ERR_REFERENTIAL_INTEGRITY": 409,
    "ERR_PARTY_GUEST_LIMIT": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = (
        error_id[4:].replace("_", " ").lower()
        if error_id.startswith("ERR_")
        else error_id
    )
    return words.capitalize() + "."


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------
ROLE_CUSTOMER = "Customer"
ROLE_ASSOCIATE = "WorkshopAssociate"
ROLE_PARTY_HOST = "PartyHost"
ROLE_MANAGER = "StoreManager"
ROLES = (ROLE_CUSTOMER, ROLE_ASSOCIATE, ROLE_PARTY_HOST, ROLE_MANAGER)
ENTITY_BACKED_ROLES = (ROLE_CUSTOMER, ROLE_ASSOCIATE, ROLE_PARTY_HOST)

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"


# ---------------------------------------------------------------------------
# Decimal / time helpers
# ---------------------------------------------------------------------------
def rhu_int(numerator, denominator=1):
    """round_half_up(numerator / denominator) to integer cents."""
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_date_string(text):
    if not isinstance(text, str) or not _DATE_RE.match(text):
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# In-memory store -- starts EMPTY on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    COLLECTIONS = (
        "stores",
        "customers",
        "staff",
        "stations",
        "plush_models",
        "consumables",
        "collection_drops",
        "workshops",
        "animals",
        "parties",
        "party_guests",
        "appointment_blocks",
        "build_ship_orders",
        "gift_cards",
        "registries",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def new_row(**fields):
    row = {
        "_seq": db.next_seq(),
        "id": str(uuid.uuid4()),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump the audit fields (PRD section 2.5)."""
    row["version"] += 1
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
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dump(row):
    if row is None:
        return None
    return {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
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
        jsonify({"meta": _meta(), "response_type": "object", "data": dump(data)}),
        status,
    )


def respond_raw(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": jsonable(data)}),
        status,
    )


def respond_list(rows, status=200):
    rows = sort_created(list(rows))
    total_count = len(rows)
    limit, offset = pagination_params()
    page = rows[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(page)) < total_count
    return (
        jsonify({"meta": meta, "response_type": "array", "data": [dump(r) for r in page]}),
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


def pagination_params():
    """PRD section 2.3: limit default 10, bounds [1, 100]; offset default 0."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        err("ERR_VALIDATION", "limit and offset must be integers.")
    if not (1 <= limit <= 100):
        err("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset < 0:
        err("ERR_VALIDATION", "offset must be non-negative.")
    return limit, offset


# ---------------------------------------------------------------------------
# Auth (validation priorities 1 and 2; PRD section 2.1)
# ---------------------------------------------------------------------------
def endpoint(*roles):
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get(HDR_ROLE)
            user_id = request.headers.get(HDR_USER)
            if not (role or "").strip():
                err("ERR_UNAUTHENTICATED", "Missing X-User-Role header.")
            if role not in ROLES:
                err("ERR_UNAUTHENTICATED", "Unrecognized X-User-Role value.")
            if role in ENTITY_BACKED_ROLES and not (user_id or "").strip():
                err(
                    "ERR_UNAUTHENTICATED",
                    "Missing X-User-ID header for an entity-backed role.",
                )
            if role not in allowed:
                err("ERR_UNAUTHORIZED", "Role %s is not permitted for this endpoint." % role)
            g.user_id = user_id or ""
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_owner(resource_customer_id):
    """Ownership check (PRD section 2.1): a Customer acts only on own resources."""
    if g.role == ROLE_CUSTOMER and g.user_id != resource_customer_id:
        err("ERR_UNAUTHORIZED", "The acting customer does not own this resource.")


# ---------------------------------------------------------------------------
# Request body + field validation helpers (priority 11 -> ERR_VALIDATION)
# ---------------------------------------------------------------------------
def body():
    """Parse the JSON body. An absent body behaves as an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        err("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        err("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        err("ERR_VALIDATION", "Field '%s' must be a non-empty string." % field)
    return value


def opt_str(data, field):
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        err("ERR_VALIDATION", "Field '%s' must be a string." % field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field)
    if not is_int(value):
        err("ERR_VALIDATION", "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        err("ERR_VALIDATION", "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        err("ERR_VALIDATION", "Field '%s' must be <= %s." % (field, maximum))
    return value


def req_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        err("ERR_VALIDATION", "Field '%s' must be a boolean." % field)
    return value


def req_enum(data, field, choices):
    value = data.get(field)
    if value not in choices:
        err(
            "ERR_VALIDATION",
            "Field '%s' must be one of %s." % (field, sorted(choices)),
        )
    return value


def req_datetime(data, field):
    value = data.get(field)
    parsed = parse_dt(value)
    if parsed is None:
        err("ERR_VALIDATION", "Field '%s' must be an ISO 8601 datetime." % field)
    return parsed


# ---------------------------------------------------------------------------
# Existence helpers (priorities 3 and 4 -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_or_404(collection, resource_id, label="resource"):
    row = getattr(db, collection).get(resource_id)
    if row is None:
        err("ERR_NOT_FOUND", "The referenced %s does not exist." % label)
    return row
