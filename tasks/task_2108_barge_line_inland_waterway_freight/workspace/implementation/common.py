"""Foundation layer: logical clock, in-memory store, errors, envelope, auth,
validation helpers and numeric/temporal utilities.

Every structural name here (header names, envelope fields, pagination params,
error ids, OCC field names) is taken verbatim from PRD.md / SCAFFOLD.yaml.
"""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING, getcontext

from flask import g, jsonify, request

getcontext().prec = 60

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_SHIPPER_NOT_FOUND": 404,
    "ERR_COMMODITY_NOT_FOUND": 404,
    "ERR_TARIFF_FILING_NOT_FOUND": 404,
    "ERR_BARGE_NOT_FOUND": 404,
    "ERR_CLEANING_ORDER_NOT_FOUND": 404,
    "ERR_FLEETING_BERTH_NOT_FOUND": 404,
    "ERR_FLEETING_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_LOCK_NOT_FOUND": 404,
    "ERR_LOCK_RESERVATION_NOT_FOUND": 404,
    "ERR_TOW_NOT_FOUND": 404,
    "ERR_BARGE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_FREIGHT_CONTRACT_NOT_FOUND": 404,
    "ERR_CARGO_CLAIM_NOT_FOUND": 404,
    "ERR_TARIFF_FILING_INVALID_STATE": 409,
    "ERR_BARGE_NOT_AVAILABLE": 409,
    "ERR_CLEANING_ORDER_INVALID_STATE": 409,
    "ERR_FLEETING_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_LOCK_RESERVATION_INVALID_STATE": 409,
    "ERR_TOW_INVALID_STATE": 409,
    "ERR_BARGE_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_CONTRACT_MOVEMENT_INVALID_STATE": 409,
    "ERR_CONTRACT_BILLING_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_STALE_TOW_VERSION": 412,
    "ERR_STALE_SHIPPER_VERSION": 412,
    "ERR_CARGO_INCOMPATIBLE": 422,
    "ERR_BARGE_CLEANLINESS_INSUFFICIENT": 422,
    "ERR_DRAFT_EXCEEDS_RESTRICTION": 422,
    "ERR_TOW_SIZE_CAP_EXCEEDED": 422,
    "ERR_BARGE_CAPACITY_EXCEEDED": 422,
    "ERR_NO_RIVER_STAGE_READING": 422,
    "ERR_NO_EFFECTIVE_TARIFF": 422,
    "ERR_NO_FUEL_INDEX_POSTING": 422,
    "ERR_TARIFF_WINDOW_OVERLAP": 409,
    "ERR_LOCK_WINDOW_CONFLICT": 409,
    "ERR_BERTH_CAPACITY_EXCEEDED": 409,
    "ERR_UNLOAD_SEQUENCE_INVALID": 422,
    "ERR_CLAIM_WINDOW_EXPIRED": 422,
    "ERR_LOCK_CLOSED": 409,
    "ERR_DUPLICATE_CUT_POSITION": 409,
    "ERR_BARGE_ALREADY_ASSIGNED": 409,
    "ERR_DUPLICATE_HULL_NUMBER": 409,
    "ERR_CLAIM_ALREADY_FILED": 409,
    "ERR_CLAIM_REVISION_LIMIT": 409,
    "ERR_ASSIGNMENT_CONTRACT_MISMATCH": 409,
    "ERR_SHORTAGE_NOT_SUPPORTED": 422,
    "ERR_NO_BILLABLE_LINES": 422,
    "ERR_SHIPPER_ON_CREDIT_HOLD": 409,
    "ERR_SHIPPER_CREDIT_EXCEEDED": 402,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = [
    "WaterwayAdmin", "TariffAnalyst", "RateAuthority", "TowboatDispatcher",
    "LockMaster", "HarborAgent", "ContractManager", "ClaimsAdjuster", "Shipper",
]
ALL_ROLES = list(ROLES)


# ---------------------------------------------------------------------------
# Logical river clock (PRD 2.5)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt
        return self.current


clock = Clock()


# ---------------------------------------------------------------------------
# In-memory store.  Starts empty on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
class Store:
    COLLECTIONS = (
        "shippers", "commodities", "compatibility_rules", "tariff_filings",
        "fuel_index_postings", "river_stage_readings", "barges",
        "cleaning_orders", "fleeting_berths", "fleeting_assignments", "locks",
        "lock_reservations", "tows", "barge_assignments", "freight_contracts",
        "cargo_claims",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def _touched_set():
    try:
        s = g.get("_touched", None)
    except Exception:
        return set()
    if s is None:
        s = set()
        g._touched = s
    return s


def touch(rec):
    """Bump version + updated_at once per row per request (PRD 2.4)."""
    if rec is None:
        return rec
    s = _touched_set()
    now = clock.now()
    if id(rec) in s:
        rec["updated_at"] = now
        return rec
    s.add(id(rec))
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1
    if "updated_at" in rec:
        rec["updated_at"] = now
    return rec


def make_record(fields, versioned=True):
    now = clock.now()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = store.next_seq()
    _touched_set().add(id(rec))
    return rec


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def dec(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(int(x))
    if isinstance(x, int):
        return Decimal(x)
    return Decimal(str(x))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def as_float(value, places):
    return float(round_half_up(value, places))


# ---------------------------------------------------------------------------
# Temporal helpers
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    m = _ISO_RE.match(text)
    if not m:
        raise ValueError("bad iso8601")
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    off = m.group(8)
    if off in (None, "Z", "z"):
        tz = timezone.utc
    else:
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(off[:2]), minutes=int(off[2:4])))
    dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _DATE_RE.match(value.strip())
    if not m:
        raise ValueError("bad date")
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    tzinfo=timezone.utc).date()


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def seconds_between(later, earlier):
    return dec((later - earlier).total_seconds())


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1, validation priorities 1-2)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def caller_id():
    return g.user_id


def caller_role():
    return g.user_role


# ---------------------------------------------------------------------------
# Body parsing / shape validation (priority 3)
# ---------------------------------------------------------------------------
_MISSING = object()


def get_body():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(body, name, required):
    if name not in body or body[name] is None:
        if required:
            _bad(name, "is required")
        return _MISSING
    return body[name]


def f_str(body, name, required=True, default=None):
    v = _present(body, name, required)
    if v is _MISSING:
        return default
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def f_bool(body, name, required=True, default=None):
    v = _present(body, name, required)
    if v is _MISSING:
        return default
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def f_int(body, name, required=True, default=None, gt=None, ge=None, le=None):
    v = _present(body, name, required)
    if v is _MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "must be an integer")
    _range(name, v, gt, ge, le)
    return v


def f_num(body, name, required=True, default=None, gt=None, ge=None, le=None):
    v = _present(body, name, required)
    if v is _MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "must be a number")
    _range(name, v, gt, ge, le)
    return v


def _range(name, v, gt, ge, le):
    if gt is not None and not v > gt:
        _bad(name, "must be greater than %s" % gt)
    if ge is not None and not v >= ge:
        _bad(name, "must be at least %s" % ge)
    if le is not None and not v <= le:
        _bad(name, "must be at most %s" % le)


def f_enum(body, name, allowed, required=True, default=None):
    v = _present(body, name, required)
    if v is _MISSING:
        return default
    if not isinstance(v, str) or v not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return v


def f_dt(body, name, required=True, default=None):
    v = _present(body, name, required)
    if v is _MISSING:
        return default
    try:
        return parse_iso(v)
    except Exception:
        _bad(name, "must be an ISO 8601 datetime")


def f_date(body, name, required=True, default=None):
    v = _present(body, name, required)
    if v is _MISSING:
        return default
    try:
        parse_date(v)
    except Exception:
        _bad(name, "must be a YYYY-MM-DD calendar date")
    return v.strip()


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3, priority 4)
# ---------------------------------------------------------------------------
_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    args = request.args
    limit, offset = 10, 0
    if "limit" in args:
        raw = args.get("limit", "").strip()
        if not _INT_RE.match(raw):
            raise ApiError("ERR_INVALID_PAGINATION")
        limit = int(raw)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset", "").strip()
        if not _INT_RE.match(raw):
            raise ApiError("ERR_INVALID_PAGINATION")
        offset = int(raw)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def sorted_rows(collection):
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def apply_filters(rows, filters):
    """filters: list of (query_param_name, record_field_name)."""
    args = request.args
    for param, field in filters:
        if param in args:
            wanted = args.get(param)
            rows = [r for r in rows if _match(r.get(field), wanted)]
    return rows


def _match(value, wanted):
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() == wanted.strip().lower()
    return str(value) == wanted


def paged_response(rows, serializer, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers (priorities 5-6)
# ---------------------------------------------------------------------------
def fetch(collection, ident, error_id):
    rec = collection.get(ident) if isinstance(ident, str) else None
    if rec is None:
        raise ApiError(error_id)
    return rec
