"""Core plumbing: errors, logical clock, in-memory store, envelope, auth, parsing.

Refined Products Pipeline Nomination & Scheduling API.
All storage is in-memory only; a fresh process starts with an empty store.
"""
import itertools
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = ("Shipper", "PipelineScheduler", "TerminalOperator", "TariffAdministrator")

# ---------------------------------------------------------------------------
# Error catalog (PRD 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_NOMINATION_NOT_FOUND": 404,
    "ERR_BATCH_TICKET_NOT_FOUND": 404,
    "ERR_MAINTENANCE_EVENT_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_CYCLE_INVALID_STATE": 409,
    "ERR_NOMINATION_INVALID_STATE": 409,
    "ERR_TICKET_INVALID_STATE": 409,
    "ERR_MAINTENANCE_INVALID_STATE": 409,
    "ERR_SETTLEMENT_INVALID_STATE": 409,
    "ERR_TARIFF_INVALID_STATE": 409,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_STALE_TERMINAL_VERSION": 412,
    "ERR_ROUTE_NOT_SERVED": 422,
    "ERR_NO_EFFECTIVE_TARIFF": 422,
    "ERR_NOMINATION_WINDOW_CLOSED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_INSUFFICIENT_NOTICE": 422,
    "ERR_QUALITY_SPEC_VIOLATION": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_MAINTENANCE_WINDOW_CONFLICT": 409,
    "ERR_TERMINAL_BAY_CONFLICT": 409,
    "ERR_SEGMENT_UNAVAILABLE": 409,
    "ERR_NOMINATION_LOCKED": 409,
    "ERR_BATCHES_IN_TRANSIT": 409,
    "ERR_SHIPPER_NOT_ACTIVE": 409,
    "ERR_TENDER_MINIMUM_NOT_MET": 422,
    "ERR_REVISION_VOLUME_INCREASE": 422,
    "ERR_TRANSMIX_RESERVE_EXCEEDED": 422,
    "ERR_INSUFFICIENT_ORIGIN_INVENTORY": 422,
    "ERR_DESTINATION_CAPACITY_EXCEEDED": 422,
    "ERR_LINEFILL_REQUIREMENT_NOT_MET": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or "Request refused: {}".format(error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q6 = Decimal("0.000001")
ZERO = Decimal("0")


def r2(value):
    return Decimal(value).quantize(Q2, rounding=ROUND_HALF_UP)


def r3(value):
    return Decimal(value).quantize(Q3, rounding=ROUND_HALF_UP)


def r6(value):
    return Decimal(value).quantize(Q6, rounding=ROUND_HALF_UP)


def dfloor(value):
    """Truncate downward to the next lower whole barrel."""
    return Decimal(value).to_integral_value(rounding=ROUND_FLOOR)


def to_decimal(value):
    """Lenient numeric coercion. Returns None when the value is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dec = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
        if not dec.is_finite():
            return None
        return dec
    return None


def to_int(value):
    """Strict-ish integer coercion (accepts integral numeric strings)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    dec = to_decimal(value)
    if dec is None:
        return None
    if dec != dec.to_integral_value():
        return None
    return int(dec)


# ---------------------------------------------------------------------------
# Instants (PRD 2.4): ISO 8601 UTC with exactly three fractional digits
# ---------------------------------------------------------------------------
_FRAC = re.compile(r"^(.*\d\d:\d\d:\d\d)\.(\d+)(.*)$")


def parse_instant(value):
    """Parse an ISO 8601 instant, returning an aware UTC datetime or None."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    match = _FRAC.match(text)
    if match:
        frac = (match.group(2) + "000000")[:6]
        text = "{}.{}{}".format(match.group(1), frac, match.group(3))
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"


# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.terminals = {}
        self.product_grades = {}
        self.segments = {}
        self.shippers = {}
        self.shipping_history = {}
        self.tariffs = {}
        self.cycles = {}
        self.nominations = {}
        self.batch_tickets = {}
        self.maintenance_events = {}
        self.settlements = {}

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_row(fields, versioned=True):
    row = {"id": new_id(), "created_at": now(), "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = now()
        row["version"] = 1
    row.update(fields)
    # A freshly created row is never "touched" again inside the same request.
    try:
        g.bumped.add(row["id"])
    except (AttributeError, RuntimeError):
        pass
    return row


def touch(row):
    """Refresh updated_at and increment version — at most once per request/row."""
    if row is None:
        return
    if "version" not in row:
        return
    bumped = getattr(g, "bumped", None)
    if bumped is None:
        bumped = set()
        g.bumped = bumped
    if row["id"] in bumped:
        return
    bumped.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = now()


def order_key(row):
    """created_at ASC with a stable creation-sequence tie-break."""
    return (row["created_at"], row["_seq"])


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(now()),
    }


def respond_object(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Authentication / authorization (PRD 2.5 ranks 1-2)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not one of the four declared roles.")
    g.user_id = str(user_id).strip()
    g.role = role
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role {} may not call this endpoint.".format(role))
    return g.user_id, g.role


def acting_role():
    return getattr(g, "role", None)


def acting_user():
    return getattr(g, "user_id", None)


# ---------------------------------------------------------------------------
# Body parsing helpers
# ---------------------------------------------------------------------------
def get_body():
    raw = request.get_data() or b""
    if not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        bad_request("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


def present(body, key):
    return key in body and body[key] is not None


def require_present(body, keys):
    for key in keys:
        if not present(body, key):
            bad_request("Required field '{}' is missing.".format(key))


def field_decimal(body, key, required=True, positive=False, non_negative=False):
    if not present(body, key):
        if required:
            bad_request("Required field '{}' is missing.".format(key))
        return None
    value = to_decimal(body[key])
    if value is None:
        bad_request("Field '{}' must be a number.".format(key))
    if positive and value <= 0:
        bad_request("Field '{}' must be strictly greater than zero.".format(key))
    if non_negative and value < 0:
        bad_request("Field '{}' must be zero or greater.".format(key))
    return value


def field_int(body, key, required=True, minimum=None, maximum=None):
    if not present(body, key):
        if required:
            bad_request("Required field '{}' is missing.".format(key))
        return None
    value = to_int(body[key])
    if value is None:
        bad_request("Field '{}' must be an integer.".format(key))
    if minimum is not None and value < minimum:
        bad_request("Field '{}' must be at least {}.".format(key, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '{}' must be at most {}.".format(key, maximum))
    return value


def field_enum(body, key, allowed, required=True):
    if not present(body, key):
        if required:
            bad_request("Required field '{}' is missing.".format(key))
        return None
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        bad_request("Field '{}' must be one of {}.".format(key, ", ".join(sorted(allowed))))
    return value


def field_bool(body, key, default=False):
    if not present(body, key):
        return default
    value = body[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    bad_request("Field '{}' must be a boolean.".format(key))


def field_string(body, key, required=True, min_len=None, max_len=None):
    if not present(body, key):
        if required:
            bad_request("Required field '{}' is missing.".format(key))
        return None
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        bad_request("Field '{}' must be a non-empty string.".format(key))
    if min_len is not None and len(value) < min_len:
        bad_request("Field '{}' must be at least {} characters.".format(key, min_len))
    if max_len is not None and len(value) > max_len:
        bad_request("Field '{}' must be at most {} characters.".format(key, max_len))
    return value


def field_instant(body, key, required=True):
    if not present(body, key):
        if required:
            bad_request("Required field '{}' is missing.".format(key))
        return None
    value = parse_instant(body[key])
    if value is None:
        bad_request("Field '{}' must be an ISO 8601 UTC instant.".format(key))
    return value


def resolve_ref(body, key, collection):
    """PRD 2.5 rank 5: body foreign keys resolve to an existing row."""
    if not present(body, key):
        return None
    value = body[key]
    if not isinstance(value, str) or value not in collection:
        fail("ERR_REFERENCE_NOT_FOUND", "Referenced '{}' does not exist.".format(key))
    return collection[value]


def lookup_path(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        fail(error_id, "Resource '{}' does not exist.".format(row_id))
    return row


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        value = to_int(raw_limit)
        if value is None or value < 1 or value > 100:
            bad_request("Query parameter 'limit' must be an integer between 1 and 100.")
        limit = value
    if raw_offset is not None:
        value = to_int(raw_offset)
        if value is None or value < 0:
            bad_request("Query parameter 'offset' must be an integer of 0 or greater.")
        offset = value
    return limit, offset


def apply_filters(rows, specs):
    """specs: list of (query_param_name, row_field_name, kind)."""
    out = list(rows)
    for param, field, kind in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "bool":
            wanted = raw.strip().lower()
            if wanted not in ("true", "false"):
                bad_request("Query parameter '{}' must be true or false.".format(param))
            flag = wanted == "true"
            out = [r for r in out if bool(r.get(field)) is flag]
        else:
            out = [r for r in out if r.get(field) == raw]
    return out


def paginate(rows, serializer):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)
